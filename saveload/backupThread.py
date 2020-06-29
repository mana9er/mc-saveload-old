from PyQt5 import QtCore
from PyQt5.QtCore import QThread
from time import time


class BackupThread(QThread):

    # Signals
    backup_finished = QtCore.pyqtSignal(tuple)  # (file_name, file_size, time_spent)

    def __init__(self, filename, format):
        super(BackupThread, self).__init__()
        self.filename = filename
        self.format = foramt

    def run(self):
        start_time = time()
        file_name, file_size = zipper.zip_dir('./', self.filename, self.format)
        end_time = time()
        self.backup_finished.emit((file_name, file_size, end_time - start_time))