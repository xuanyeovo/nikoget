import argparse
import colorlog
import json
import traceback
import mutagen.mp3
import mutagen.mp4
import mutagen.id3
import io
import os
import re
import time
from typing import Callable
from tqdm import tqdm
from nikoget import *
from nikoget.common import *
from nikoget.select import *
from nikoget.utils import *

PLUGINS = PluginLoader()

MIME_EXTENSIONS = {
    'audio/mp3': '.mp3',
    'audio/x-mpeg-3': '.mp3',
    'audio/mpeg': '.mp3',
    'audio/mpeg3': '.mp3',
    'audio/mp4': '.m4a',
    'video/mp4': '.mp4',
    'video/x-msvideo': '.avi',
    'video/quicktime': '.mov',
    'video/x-flv': '.flv',
}

global SUBCOMMAND_ARGS
SUBCOMMAND_ARGS = None

def try_compress_image(image_data: bytes, limit=2097152):
    logger = colorlog.getLogger('nikoget')

    if len(image_data) < limit:
        logger.debug(f'Image size is smaller than {limit} bytes. Skipping compression')
        return image_data

    try:
        import numpy as np
    except:
        logger.warning('Cannot import numpy. Skipping compression')
        return image_data

    try:
        import cv2
    except:
        logger.warning('Cannot import opencv. Skipping compression')
        return image_data

    logger.info('Image size is {}, compressing...'.format(len(image_data)))

    img = cv2.imdecode(np.frombuffer(image_data, dtype=np.uint8), cv2.IMREAD_ANYCOLOR)

    current_size = len(image_data)
    quality = 100
    while current_size >= limit:
        quality -= 2
        if quality < 5:
            break

        compressed = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])[1]
        current_size = len(compressed)

    logger.info(f'Image compression has done. Final quality is {quality}. Final size is {current_size}')

    return compressed.tobytes()

def get_mime_by_ext(ext):
    '''
    Get the corresponding mime type by a extension name
    If the mime type is not found, it returns None

    Example:
        get_mime_by_ext('.mp3') -> 'audio/mp3'
        get_mime_by_ext('.mov') -> 'video/quicktime'
        get_mime_by_ext('java') -> None
    '''
    for k in MIME_EXTENSIONS.keys():
        if MIME_EXTENSIONS[k] == ext:
            return k

def fix_path(directory, file_name)-> str:
    '''
    Name of a file include following characters can not be created successfully:

    * (In Windows(NT) OS)
        :*?"<>|

    * (In Darwin)
        $?|:

    * (In Android emulated fs)
        "
    '''

    file_name = re.sub('"', '`', re.sub(':|\\*|\\?|\\||\\$', '', file_name)) \
        .replace('<', '(').replace('>', ')') \
        .replace('/', ' ')

    return os.path.join(directory, file_name)

def download_audio(args, descriptor):
    '''
    Download a AudioDescriptor object

    It detects available meta information and patches them into the
    final audio file automatically, including the album cover.
    '''

    logger = colorlog.getLogger('nikoget')

    audio_tmpfile_path = fix_path(args.output, 'tmp_' + descriptor.name)

    select = args.select.split(',')

    if 'audio' in select:
        logger.info(f'Downloading audio "{descriptor.name}"')
        audio_fd = open(audio_tmpfile_path, 'wb')

        # Start the DownloadContext
        audio_ctx = descriptor.download(audio_fd)
        audio_ctx.run()

        # Wait for the mime type is ready to be read
        while audio_ctx.headers_ready == False:
            time.sleep(0.1)

        if audio_ctx.mime in MIME_EXTENSIONS:
            extension_name = MIME_EXTENSIONS[audio_ctx.mime]
        else:
            extension_name = ''
        audio_file_path = fix_path(args.output, descriptor.name + extension_name)

        pbar = tqdm(desc=descriptor.short_name, unit='MB', leave=False)

        # Show the progress of audio download task
        while audio_ctx.run_status == TaskStatus.running:
            pbar.total = round(audio_ctx.total_size / 1048576, 2)
            pbar.n = round(audio_ctx.downloaded_size / 1048576, 2)
            pbar.refresh()

        audio_fd.close()
        pbar.close()

        # Download the album cover
        if hasattr(descriptor, 'download_cover') and callable(descriptor.download_cover) and not args.no_cover:
            logger.info(f'Download album cover for audio "{descriptor.name}"')

            out = io.BytesIO()
            pbar.desc = descriptor.short_name + '(Cover Image)'
            cover_ctx = descriptor.download_cover(out)
            cover_ctx.run()
            while cover_ctx.run_status == TaskStatus.running:
                pbar.total = cover_ctx.total_size / 1048576
                pbar.n = cover_ctx.downloaded_size / 1048576
                pbar.refresh()
            pbar.close()
        else:
            out = None
            cover_ctx = None

        if out is not None:
            cover = out.getvalue()
            cover_mime = cover_ctx.mime
        else:
            cover = None
            cover_mime = None

    if 'lyrics' in select and descriptor.lyrics is not None:
        open(fix_path(args.output, descriptor.name + '.lrc'), 'w').write(descriptor.lyrics)

    if 'audio' in select:
        patch_audio(
            args,
            audio_tmpfile_path, audio_ctx.mime,
            descriptor,
            cover, cover_mime
        )

        os.rename(audio_tmpfile_path, audio_file_path)

def patch_audio(args, audio_path, audio_mime, descriptor, cover=None, cover_mime=None):
    '''
    Patch the audio file with the meta information

    Supported file formats:
        * MP3
    '''

    if cover is not None and not args.no_compress_cover:
        cover = try_compress_image(cover)

    logger = colorlog.getLogger('nikoget')

    if audio_mime in ['audio/mp3', 'audio/mpeg', 'audio/mpeg3', 'audio/x-mpeg-3']:

        logger.debug('Patching MP3 file')

        mp3 = mutagen.mp3.EasyMP3(audio_path)
        mp3.update(descriptor.as_easymp3_dict())
        mp3.save()

        mp3 = mutagen.id3.ID3(audio_path)

        if descriptor.lyrics is not None:
            mp3.add(mutagen.id3.USLT(encoding=3, desc='Lyrics', lang='eng', text=descriptor.lyrics))

        if cover is not None:
            mp3.add(mutagen.id3.APIC(encoding=3, desc='Cover', mime=cover_mime, data=cover))

        mp3.save()

    elif audio_mime in ['audio/mp4', 'video/mp4']:

        logger.debug('Patching MP4/M4A file')

        mp4 = mutagen.mp4.MP4(audio_path)
        mp4.update(descriptor.as_mp4_dict())

        if cover is not None:
            if cover_mime == 'image/png':
                cover_format = mutagen.mp4.MP4Cover.FORMAT_PNG
            elif cover_mime in ['image/jpg', 'image/jpeg']:
                cover_format = mutagen.mp4.MP4Cover.FORMAT_JPEG
            else:
                logger.warning(f'File format of the cover image({cover_mime}) is not supported by MP4. It may not work')
                cover_format = None

            mp4['covr'] = [mutagen.mp4.MP4Cover(data=cover, imageformat=cover_format)]

        mp4.save()

    else:

        logger.warning(f'Unsupported audio format {audio_mime}. Meta info cannot be embedded')

def download(args):
    global SUBCOMMAND_ARGS
    SUBCOMMAND_ARGS = args

    logger = colorlog.getLogger('nikoget')

    def deliver_download(descriptor):
        if isinstance(descriptor, ThinAudioDescriptor):
            descriptor = descriptor.to_full()
            download_audio(args, descriptor)

        elif isinstance(descriptor, AudioDescriptor):
            download_audio(args, descriptor)

    for url in args.url:
        if target := match_url(url, PLUGINS):
            logger.debug(f'Matched URL: {url}')
            logger.debug('Using plugin \'{0}\'\r\n'.format(target.id()))
            logger.info('Resolving URL...')
            try:
                descriptors = target.resolve_url(url)
                if args.all or len(descriptors) == 1:
                    for i in descriptors:
                        deliver_download(i)
                else:
                    logger.error('Selecting multiple descriptors is not supported at present')
                    exit(1)

                logger.info('Done')

            except Exception as err:
                logger.error('Unable to resolve url. Error detail:')
                traceback.print_exception(err)
        else:
            logger.warning(f'Unmatched URL: {url}')

def patch(args):
    global SUBCOMMAND_ARGS
    SUBCOMMAND_ARGS = args

    def deliver_patch(descriptor):
        if isinstance(descriptor, ThinAudioDescriptor):
            descriptor = descriptor.to_full()

        if isinstance(descriptor, AudioDescriptor):
            mime = get_mime_by_ext(os.path.splitext(args.file)[-1])

            if mime == None:
                logger.error('Unknown file format')
                exit(1)

            if hasattr(descriptor, 'download_cover') and callable(descriptor.download_cover) and not args.no_cover:
                logger.info(f'Download album cover for audio "{descriptor.name}"')

                out = io.BytesIO()
                pbar = tqdm(desc = descriptor.short_name + '(Cover Image)')
                cover_ctx = descriptor.download_cover(out)
                cover_ctx.run()
                while cover_ctx.run_status == TaskStatus.running:
                    pbar.total = cover_ctx.total_size / 1048576
                    pbar.n = cover_ctx.downloaded_size / 1048576
                    pbar.refresh()
                pbar.close()

                cover = out.getvalue()
                cover_mime = cover_ctx.mime

            else:
                cover = None
                cover_mime = None

            patch_audio(args, args.file, mime, descriptor, cover=cover, cover_mime=cover_mime)

    logger = colorlog.getLogger('nikoget')

    if not os.path.exists(args.file):
        logger.error(f'File "{args.file}" cannot be found')
        exit(1)
    elif not os.path.isfile(args.file):
        logger.error(f'"{args.file}" is not a regular file')
        exit(1)

    if target := match_url(args.url, PLUGINS):
        logger.debug(f'Matched URL: {args.url}')
        logger.debug('Using plugin \'{}\'\r\n'.format(target.id()))
        logger.info('Resolving URL...')
        try:
            descriptors = target.resolve_url(args.url)
            if len(descriptors) == 1:
                deliver_patch(descriptors[0])
            else:
                items = list(map(lambda x:SelectItem(x, x.name), descriptors))
                selector = Select(items)

                if descriptor := selector.select_one():
                    deliver_patch(descriptor)
                else:
                    logger.info('Aborted')
                    exit(0)

            logger.info('Done')
        except Exception as err:
            logger.error('Unable to resolve url. Error detail:')
            traceback.print_exception(err)
    else:
        logger.error(f'Unmatched URL: {args.url}')
        exit(1)

def main():
    handler = colorlog.StreamHandler()
    handler.setFormatter(colorlog.ColoredFormatter(
        '%(log_color)s[%(levelname)s] %(asctime)s %(name)s: %(message)s'
    ))

    logger = colorlog.getLogger('nikoget')
    logger.setLevel(colorlog.INFO)
    logger.addHandler(handler)

    parser = argparse.ArgumentParser(
        prog='nikoget',
        description='Download multimedia file from some internet sites'
    )
    parser.add_argument('--debug', action='store_true')
    subparsers = parser.add_subparsers(help='Subcommand', required=True)

    download_parser = subparsers.add_parser('download', help='Download something from the given URL')
    download_parser.add_argument('url', nargs='+')
    download_parser.add_argument(
        '-o', '--output',
        help='Output folder',
        default='./')
    download_parser.add_argument(
        '-y', '--yes', '--all',
        dest='all',
        help='Automatically download all files when you need to select multiple files', action='store_true')
    download_parser.add_argument(
        '--no-cover',
        dest='no_cover',
        action='store_true',
        help='Do not download album cover for audio(s)')
    download_parser.add_argument(
        '--no-compress-cover',
        dest='no_compress_cover',
        action='store_true',
        help='Do not compress album cover larger than 2MB')
    download_parser.add_argument(
        '-s', '--select',
        dest='select',
        default='audio,lyric',
        help='Select what resource to download')
    download_parser.set_defaults(func=download)

    patch_parser = subparsers.add_parser('patch', help='Patch a file')
    patch_parser.add_argument(
        '--no-cover',
        dest='no_cover',
        action='store_true',
        help='Do not download album cover for audio(s)')
    patch_parser.add_argument(
        '--no-compress-cover',
        dest='no_compress_cover',
        action='store_true',
        help='Do not compress album cover larger than 2MB')
    patch_parser.add_argument('file', help='File to be patched')
    patch_parser.add_argument('url')
    patch_parser.set_defaults(func=patch)

    args = parser.parse_args()

    # Debug logs
    if args.debug:
        logger.setLevel(colorlog.DEBUG)

    args.func(args)

if __name__ == '__main__':
    main()
