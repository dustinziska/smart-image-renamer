#! /usr/bin/env python

# smart-image-renamer
#
# Author: Ronak Gandhi (ronak.gandhi@ronakg.com)
# Project Home Page: https://github.com/ronakg/smart-image-renamer
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Smart Image Renamer main module"""

"""IMG Rename Imports"""
import argparse
import itertools
import os
import re
import shutil

"""MOV Rename Imports"""
import sys
import time
import struct
import glob

from PIL import Image
from PIL.ExifTags import TAGS

from _version import __version__

class Atom():
    """
    MOV file atom.
    'type' and 'header' are bytes
    """
    def __init__(self, type, header, size):
        self.type = type
        self.name = self.type.decode()
        self.header = header
        self.size = size

class NotAnImageFile(Exception):
    """This file is not an Image"""
    pass

class InvalidExifData(Exception):
    """Could not find any EXIF or corrupted EXIF"""
    pass

def get_cmd_args():
    """Get, process and return command line arguments to the script
    """
    help_description = '''
Smart Image Renamer

Rename your photos in bulk using information stored in EXIF.
'''

    help_epilog = '''
Format string for the file name is defined by a mix of custom text and following tags enclosed in {}:
  YYYY        Year
  MM          Month
  DD          Day
  hh          Hours
  mm          Minutes
  ss          Seconds
  Seq         Sequence number
  Artist      Artist
  Make        Camera Make
  Model       Camera Model
  Folder      Parent folder of the image file
  File        Current Filename

Examples:
  Format String:          {YYYY}-{MM}-{DD}-{Folder}-{Seq}
  File Name:              2014-05-09-Wedding_Shoot-001.JPEG
                          2014-05-09-Wedding_Shoot-002.JPEG

  Format String:          {YYYY}{DD}{MM}_{Model}_Beach_Shoot_{Seq}
  File Name:              20140429_PENTAX K-x_Beach_Shoot_001.JPEG
                          20140429_PENTAX K-x_Beach_Shoot_002.JPEG
    '''

    parser = argparse.ArgumentParser(description=help_description,
                                     formatter_class=argparse.RawTextHelpFormatter,
                                     epilog=help_epilog)
    parser.add_argument('-f', dest='format', required=True, type=str,
                        help='Format of the new image file name')
    parser.add_argument('-m', dest='movformat', required=True, type=str,
                        help='Format of the new mov file name')
    parser.add_argument('-s', dest='sequence', type=int, default=1,
                        help='Starting sequence number (default: 1)')
    parser.add_argument('-r', dest='recursive', default=False,
                        action='store_true',
                        help='Recursive mode')
    parser.add_argument('-i', dest='hidden', default=False,
                        action='store_true', help='Include hidden files')
    parser.add_argument('-c', dest='copy', default=False,
                        action='store_true', help='Copy file')
    parser.add_argument('-d', dest='destination', default="", type=str,
                        help='Copy to destination')
    parser.add_argument('-t', dest='test', default=False, action='store_true',
                        help='Test mode. Don\'t apply changes.')
    parser.add_argument('-V', '--version', action='version',
                        version='%(prog)s {}'.format(__version__))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-v", "--verbose", action="store_true")
    group.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument('input', nargs='+',
                        help='Absolute path to file or directory')

    return parser.parse_args()

def get_exif_data(img_file):
    """Read EXIF data from the image.

    img_file: Absolute path to the image file

    Returns: A dictionary containing EXIF data of the file

    Raises: NotAnImageFile if file is not an image
            InvalidExifData if EXIF can't be processed
    """
    try:
        img = Image.open(img_file)
    except (OSError, IOError):
        raise NotAnImageFile

    try:
        # Use TAGS module to make EXIF data human readable
        exif_data = {
            TAGS[k]: v
            for k, v in img._getexif().items()
            if k in TAGS
        }
    except AttributeError:
        raise InvalidExifData

    # Add image format to EXIF
    exif_data['format'] = img.format
    return exif_data

def atom_header_correct(movie_file, atom):
    """
    Check if atom header is correct.
    :param movie_file:
    :param atom:
    :return:
    """
    if movie_file.read(8)[4:8] == atom.header:
        return True
    else:
        return False
    
def find_atom(movie_file, atom):
    """
    Search for desired atom.
    :param movie_file:
    returns False if not found
    """

    while True:
        try:
            atom_size, atom_type = struct.unpack('>L4s', movie_file.read(8))
        except:
            break

        if atom_type == atom.type and atom_header_correct(movie_file, atom):
            return True

        else:
            if atom_size < 8:
                break
            movie_file.seek(atom_size - 8, os.SEEK_CUR)

    return False
    
def seek_to_atom_header_end(movie_file, atom):
    """
    Seek to the end of 'atom' in 'movie_file'.
    """
    movie_file.seek(atom.size, 1)

def get_file_timestamps(filename, timestamp_format):
    """
    Get list of system and QT timestamps from file
    """

    file_timestamps = {'file': [0, 0]}  # Will contain all time values we will find

    # Get file mtime
    file_timestamps['file'][1] = os.path.getmtime(filename)
    
    # Get moov timestamps
    file_timestamps.update(get_mov_data(filename))
    
    # Format all timestamps according to provided template
    try:
        format_time(file_timestamps, timestamp_format)
    except ValueError:
        print('Error in time format "{0}."'.format(timestamp_format))
        sys.exit(1)
    
    return file_timestamps
    
def format_time(timestamps, time_format):
    """
    Format timestamps according to provided template
    """
    for timestamp_type in timestamps:
        for time_item in range(len(timestamps[timestamp_type])):
            timestamps[timestamp_type][time_item] = time.strftime(
                time_format,
                time.localtime(timestamps[timestamp_type][time_item])
            )
    
def read_timestamps(filename):
    """
    Read creation and modification time given the beginning of atom
    """
    QT_EPOCH = 2082844800
    filename.seek(4, 1)
    creation_time = struct.unpack('>I', filename.read(4))[0] - QT_EPOCH
    modification_time = struct.unpack('>I', filename.read(4))[0] - QT_EPOCH
    return [creation_time, modification_time]
    
def get_mov_data(filename):
    """
    Get movie creation time from QT movie atom. Returns zero timestamps in case of error.
    Looks in 'moov', 'trak' and 'mdia' first found headers
    """
    timestamps = {'moov': [0, 0], 'trak': [0, 0], 'mdia': [0, 0]}

    with open(filename, 'r+b') as movie_file:
        moov_atom = Atom(b'moov', b'mvhd', 88)
        if not find_atom(movie_file, moov_atom):
            return timestamps

        timestamps[moov_atom.name] = read_timestamps(movie_file)
        seek_to_atom_header_end(movie_file, moov_atom)

        trak_atom = Atom(b'trak', b'tkhd', 72)
        if not find_atom(movie_file, trak_atom):
            return timestamps
        timestamps[trak_atom.name] = read_timestamps(movie_file)
        seek_to_atom_header_end(movie_file, trak_atom)

        mdia_atom = Atom(b'mdia', b'mdhd', 12)
        if not find_atom(movie_file, mdia_atom):
            return timestamps
        timestamps[mdia_atom.name] = read_timestamps(movie_file)

    return timestamps
    
def move2dest(old, new, copy=False):
    parent = os.path.dirname(new)
    if not os.path.exists(parent):
        os.makedirs(parent)
    if copy:
        shutil.copy2(old, new)
    else:
        shutil.move(old, new)

if __name__ == '__main__':
    skipped_files = []
    args = get_cmd_args()

    input_paths = [os.path.abspath(input) for input in args.input]
    input_format = args.format
    input_mov_format = args.movformat
    verbose = args.verbose
    quiet = args.quiet
    sequence_start = args.sequence
    test_mode = args.test
    recursive = args.recursive
    include_hidden = args.hidden
    destination = os.path.expanduser(args.destination)
    copymode = args.copy

    for input_path in input_paths:
        for root, dirs, files in os.walk(input_path):
            # Skip hidden directories unless specified by user
            if not include_hidden and os.path.basename(root).startswith('.'):
                continue

            # Initialize sequence counter
            # Use no of files to determine padding for sequence numbers
            seq = itertools.count(start=sequence_start)
            seq_width = len(str(len(files)))

            print('Processing folder: {}'.format(root))
            for f in sorted(files):
                # Skip hidden files unless specified by user
                if not include_hidden and f.startswith('.'):
                    continue

                old_file_name = os.path.join(root, f)
                try:
                    # Get EXIF data from the image
                    exif_data = get_exif_data(old_file_name)
                except NotAnImageFile:
                    # Not an Image, try for Movie
                    timestamps = get_file_timestamps(old_file_name, input_mov_format)
                    print("Movie Timestamps = " + str(timestamps['moov'][0]))
                    continue
                except InvalidExifData:
                    skipped_files.append((old_file_name, 'No EXIF data found'))
                    continue

                # Find out the original timestamp or digitized timestamp from the EXIF
                img_timestamp = (exif_data.get('DateTimeOriginal') or exif_data.get('DateTimeDigitized'))
                # TODO
                print("Image TimeStamp = " + str(img_timestamp))

                if not img_timestamp:
                    skipped_files.append((old_file_name, 'No timestamp found in image EXIF'))
                    continue

                # Extract year, month, day, hours, minutes, seconds from timestamp
                img_timestamp =\
                    re.search(r'(?P<YYYY>\d\d\d?\d?):(?P<MM>\d\d?):(?P<DD>\d\d?) '
                              '(?P<hh>\d\d?):(?P<mm>\d\d?):(?P<ss>\d\d?)',
                              img_timestamp.strip())

                if not img_timestamp:
                    skipped_files.append((old_file_name,
                                          'Timestamp not in correct format'))
                    continue

                # Generate data to be replaced in user provided format
                new_image_data = {'Artist': exif_data.get('Artist', ''),
                                  'Make': exif_data.get('Make', ''),
                                  'Model': exif_data.get('Model', ''),
                                  'Folder': os.path.basename(root),
                                  'File': os.path.splitext(f)[0],
                                  'Seq': '{0:0{1}d}'.format(next(seq), seq_width),
                                  'ext': exif_data.get('format', '')
                                  }
                new_image_data.update(img_timestamp.groupdict())

                # Generate new file name according to user provided format
                new_file_name = (input_format + '.{ext}').format(**new_image_data)
                if destination:
                    new_file_name_complete = os.path.join(destination, new_file_name)
                else:
                    new_file_name_complete = os.path.join(root, new_file_name)

                # Don't rename files if we are running in test mode
                if not test_mode:
                    try:
                        if copymode:
                            move2dest(old_file_name, new_file_name_complete, copy=True)
                        else:
                            move2dest(old_file_name, new_file_name_complete)
                    except OSError:
                        skipped_files.append((old_file_name,
                                              'Failed to rename file'))
                        continue

                if verbose:
                    print('{0} --> {1}'.format(old_file_name,
                                             new_file_name_complete))
                elif not quiet:
                    print('{0} --> {1}'.format(f, new_file_name))

            # Folder processed
            print('')

            # Break if recursive flag is not present
            if not recursive:
                break

    # Print skipped files
    if skipped_files and not quiet:
        print('\nSkipped Files:\n\t' + '\n\t'.join([file + ' (' + error + ')'
                                                    for file, error in
                                                    skipped_files]))
