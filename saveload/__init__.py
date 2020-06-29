from .saveload import SaveLoader

# list dependencies
dependencies = ['mcBasicLib']


def load(logger, core):
    # Function "load" is required by mana9er-core.
    from os import path
    config_file = path.join(core.init_cwd, 'saveload', 'config.json')
    info_file = path.join(core.init_cwd, 'saveload', 'info.json')
    return SaveLoader(logger, core, config_file, info_file)