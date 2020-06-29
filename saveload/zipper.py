import shutil
from os import path

def zip_dir(src_path, zip_name, format='zip'):
    '''
    Make an archive file containing files in the source directory.
    Returns the file name and the total size of the archive file.
    You can choose 'zip' or 'tar' format.
    '''
    z = shutil.make_archive(zip_name, format, src_path)
    return z, path.getsize(z)

def unzip(zip_name, tar_path):
    '''
    Extract a zip file to the target path.
    Will overwrite the files in the target path.
    '''
    shutil.unpack_archive(zip_name, tar_path)
