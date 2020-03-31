import json
import os
import time
from . import zip
from . import parser
from PyQt5 import QtCore
from PyQt5.QtCore import QTimer

__all__ = ['SaveLoader']


class SaveLoader(QtCore.QObject):
    cmd_prefix = '!sl'

    def __init__(self, logger, core, config_file, info_file):
        super(SaveLoader, self).__init__(core)
        self.core = core
        self.logger = logger
        self.info_file = info_file

        # load config
        self.configs = {}
        self.logger.info('Loading configs...')
        with open(config_file, 'r', encoding='utf-8') as cf:
            self.configs = json.load(cf)

        # load backup info
        if os.path.exists(self.info_file):
            self.logger.info('Loading backup infomation...')
            with open(self.info_file, 'r', encoding='utf-8') as sf:
                info_obj = json.load(sf)
                self.backups = info_obj['backups']
                self.auto_backup_counted = info_obj['auto-backup-counted']
        else:
            self.logger.warning('Failed to find previous backup infomation')
            self.logger.info('Creating info file...')
            self.backups = []
            self.auto_backup_counted = 0
            self.update_info()
        
        # connect signals and slots
        self.core.notifier.sig_input.connect(self.on_player_input)
        self.core.core_quit.connect(self.on_core_quit)
        self.core.sig_server_stop.connect(self.maybe_restore_server)

        self.cmd_list = {
            'help': self.help,
            'backup': self.backup,
            'list': self.show_list,
            'restore': self.restore,
            'confirm': self.confirm,
            'cancel': self.cancel,
        }

        self.restore_to = None
        self.need_confirm = False
        self.restoring = False

        self.valid_timer = QTimer(self)
        self.valid_timer.timeout.connect(self.confirm_timeout)
        self.count_down_timer = QTimer(self)
        self.count_down_timer.timeout.connect(self.restore_count_down)
        self.count_down = -1
        if self.configs['auto-backup-interval-hour'] != 0:  # auto-backup enabled
            self.auto_backup_timer = QTimer(self)
            self.auto_backup_timer.timeout.connect(self.auto_backup)
            self.auto_backup_timer.timeout.connect(self.reset_auto_backup_interval)
            interval = self.configs['auto-backup-interval-hour']
            self.auto_backup_timer.start(interval * 3600 * 1000 - self.auto_backup_counted)
            self.auto_backup_count_start_time = time.time()

    def update_info(self):
        json.dump(
            {
                'backups': self.backups,
                'auto-backup-counted': self.auto_backup_counted,
            }, 
            open(self.info_file, 'w', encoding='utf-8'),
            indent=2
        )

    def size_wrap(self, file_size):
        byte_size = file_size
        kb = byte_size / 1024.0
        mb = kb / 1024.0
        if (mb < 1):
            return '{:.2f} KB'.format(kb)
        gb = mb / 1024.0
        if (gb < 1):
            return '{:.2f} MB'.format(mb)
        return '{:.2f} GB'.format(gb)

    def server_say(self, text):
        self.core.write_server('/say {}'.format(text))

    def server_tell(self, player, text):
        self.core.write_server('/tellraw {} {}'.format(player.name, json.dumps({'text': text, 'color': 'yellow'})))
    
    def server_warn(self, player, text):
        self.core.write_server('/tellraw {} {}'.format(player.name, json.dumps({'text': text, 'color': 'red'})))

    def unknown_command(self, player):
        self.logger.warning('unknown command')
        self.server_tell(player, 'Unknown command. Type "!sl help" for help.')
    
    def on_player_input(self, pair):
        '''
        Acceptable commands:
        !sl help
        !sl backup [remark]
        !sl list
        !sl restore <last | int:id>
        !sl confirm
        !sl cancel
        '''
        self.logger.debug('SaveLoader.on_player_input called')
        player = pair[0]
        text = pair[1]
        text_list = parser.split_text(text)

        if text_list[0] == self.cmd_prefix:
            if len(text_list) > 1 and text_list[1] in self.cmd_list.keys():
                try:
                    self.cmd_list[text_list[1]](player, text_list)
                except AttributeError as err:
                    self.logger.error('Fatal: AttributeError raised.')
                    print(err)
                    self.server_warn(player, 'saveload internal error raised.')
                except KeyError as err:
                    self.logger.error('Fatal: KeyError raised.')
                    print(err)
                    self.server_warn(player, 'saveload internal error raised.')
            else:
                self.unknown_command(player)

    def on_core_quit(self):
        self.logger.debug('SaveLoader.on_core_quit called')
        self.auto_backup_counted = time.time() - self.auto_backup_count_start_time
        self.update_info()

    def help(self, player, text_list):
        self.logger.debug('SaveLoader.help called')
        self.server_tell(
            player, 
            ('Welcome to saveload!\n'
            'You are able to use the following commands:\n'
            '"!sl help": show this help message.\n'
            '"!sl list": list the existing backups.\n'
            '"!sl backup [remark]": make a backup for the current server. You can add a remark by adding this optional argument to the end of the command.\n'
            '"!sl restore <last | int:id>": use the selected backup to restore the server. You can use keyword "last" to indicate the latest backup. This command requires confirmation.\n'
            '"!sl confirm": confirm the restoration. Once confirmed, the count down will start immediately.\n'
            '"!sl cancel": cancel the restoration. Can be called before or after confirmation.\n')
        )

    def backup(self, player, text_list):
        self.logger.debug('SaveLoader.backup called')
        if len(text_list) > 3:
            self.unknown_command(player)
            return

        if self.configs['permission-level'] == 'op':
            if not player.is_op():
                self.server_tell(player, 'Only op can make a backup. Permission denied.')
                return
        
        remark = '' if len(text_list) < 3 else text_list[2]
        time_str = time.strftime('%Y-%m-%d %H.%M.%S', time.localtime())
        if self.configs['save-path'] == '':
            file_name = os.path.join(self.core.init_cwd, 'saveload', 'backup_' + time_str)
        else:
            file_name = os.path.join(self.configs['save-path'], 'backup_' + time_str)

        self.core.write_server('/save-off')
        self.core.write_server('/save-all flush')
        
        start_time = time.time()
        file_name, file_size = zip.zip_dir('./', file_name)
        end_time = time.time()

        self.core.write_server('/save-on')

        zip_size = self.size_wrap(file_size)
        self.backups.append(
            {
                'file_name': file_name,
                'time': time_str,
                'player': player.name,
                'remark': remark,
                'size': zip_size,
            }
        )

        info_str = 'Player {} successfully made a backup at {}'.format(player.name, time_str)
        if remark != '':
            info_str += ' with a remark: {}'.format(remark)
        self.server_say(info_str)
        info_str = 'Backup size: {}. Cost: {:.1f} seconds.'.format(zip_size, end_time - start_time)
        self.server_say(info_str)

        if len(self.backups) > self.configs['max-backup-num']:  # max-backup-num exceeded, delete the oldest backup
            os.remove(self.backups[0]['file_name'])
            del self.backups[0]
    
        self.update_info()

    def restore(self, player, text_list):
        self.logger.debug('SaveLoader.restore called')
        if len(text_list) != 3:
            self.unknown_command(player)
            return

        if text_list[2] == 'last':
            self.restore_to = -1
        else:
            try:
                index = int(text_list[2])
            except ValueError:
                self.unknown_command(player)
                return
            
            if index < 0 or index >= len(self.backups):
                self.server_tell(player, 'Please type a valid index.')
                return
            self.restore_to = index

        if self.configs['permission-level'] == 'op':
            if not player.is_op():
                self.server_tell(player, 'Only op can make a backup. Permission denied.')
                return
        
        self.need_confirm = True
        valid_time = self.configs['restore-valid-sec']
        self.server_say('Player {} requested for restoring the server to: {}'.format(player.name, self.backups[self.restore_to]['time']))
        self.server_tell(player, 'Please type "!sl confirm" to CONFIRM your operation or type "!sl cancel" to cancel.')
        self.server_tell(player, 'If not confirmed, the restoration will be cancelled automatically after {} seconds.'.format(valid_time))
        self.valid_timer.start(valid_time * 1000)

    def show_list(self, player, text_list):
        self.logger.debug('SaveLoader.show_list called')
        if len(text_list) != 2:
            self.unknown_command(player)
            return

        self.server_tell(player, 'Backups:')
        for i in range(len(self.backups)):
            backup_info = self.backups[i]
            remark = 'None' if backup_info['remark'] == '' else backup_info['remark']
            info_str = '{:d}: made by {} at {}, remark: {}'.format(i, backup_info['player'], backup_info['time'], remark)
            self.server_tell(player, info_str)
        
        if len(self.backups) == 0:
            self.server_tell(player, 'There is no existing backup.')
        
    def confirm(self, player, text_list):
        self.logger.debug('SaveLoader.confirm called')
        if len(text_list) != 2:
            self.unknown_command(player)
            return

        if self.configs['permission-level'] == 'op':
            if not player.is_op():
                self.server_tell(player, 'Only op can make a backup. Permission denied.')
                return

        if self.need_confirm:
            self.valid_timer.stop()
            self.count_down = self.configs['restore-count-down-sec'] + 1
            self.count_down_timer.start(1000)
            self.server_tell(player, 'You have confirmed the restoration. Count down will start immediately.')
        else:
            self.server_tell(player, 'Nothing to confirm.')

    def cancel(self, player, text_list):
        self.logger.debug('SaveLoader.cancel called')
        # Will not check if the command contains only 2 arguments
        # Because cancelation is a high-priority operation
        self.count_down_timer.stop()
        self.count_down = -1
        self.restore_to = None
        if self.need_confirm:
            self.server_say('The restoration has been cancelled by {}'.format(player.name))
        self.need_confirm = False

    def auto_backup(self):
        self.logger.debug('SaveLoad.auto_backup called')
        if not self.core.server_running:
            return

        remark = 'Auto-backup'
        time_str = time.strftime('%Y-%m-%d %H.%M.%S', time.localtime())
        if self.configs['save-path'] == '':
            file_name = os.path.join(self.core.init_cwd, 'saveload', 'backup_' + time_str)
        else:
            file_name = os.path.join(self.configs['save-path'], 'backup_' + time_str)

        self.core.write_server('/save-off')
        self.core.write_server('/save-all flush')
        
        start_time = time.time()
        file_name, file_size = zip.zip_dir('./', file_name)
        end_time = time.time()

        self.core.write_server('/save-on')

        zip_size = self.size_wrap(file_size)
        self.backups.append(
            {
                'file_name': file_name,
                'time': time_str,
                'player': 'Auto-backup',
                'remark': remark,
                'size': zip_size
            }
        )

        info_str = 'Auto-backup was successfully made at {}'.format(time_str)
        self.server_say(info_str)
        info_str = 'Backup size: {}. Cost: {:.1f} seconds.'.format(zip_size, end_time - start_time)
        self.server_say(info_str)

        if len(self.backups) > self.configs['max-backup-num']:  # max-backup-num exceeded, delete the oldest backup
            os.remove(self.backups[0]['file_name'])
            del self.backups[0]
    
        self.update_info()

    def reset_auto_backup_interval(self):
        self.logger.debug('SaveLoad.reset_auto_backup_interval called')
        self.auto_backup_timer.stop()
        interval = self.configs['auto-backup-interval-hour']
        self.auto_backup_timer.start(interval * 3600 * 1000)
        self.auto_backup_count_start_time = time.time()

    def restore_count_down(self):
        self.logger.debug('SaveLoader.restore_count_down called')
        self.count_down -= 1
        if self.count_down == 0:
            self.count_down_timer.stop()
            self.core.stop_server()
            self.restoring = True
            return
        self.server_say('The server will be restored after {:d} seconds!'.format(self.count_down))

    def confirm_timeout(self):
        self.logger.debug('SaveLoader.confirm_timeout called')
        self.restore_to = None
        self.need_confirm = False
        self.valid_timer.stop()

    def maybe_restore_server(self):
        if not self.restoring:
            return

        self.logger.debug('Restoring the server...')
        backup_file = self.backups[self.restore_to]['file_name']
        self.logger.debug('Unzipping {}'.format(backup_file))
        zip.unzip(backup_file, './')
        self.logger.debug('Unzipping finished')

        # Reset these marks
        self.restoring = False
        self.restore_to = None
        self.need_confirm = False

        self.logger.debug('Starting the server')
        self.core.start_server()
