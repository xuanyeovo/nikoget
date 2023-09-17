import argparse
import colorlog
import json
import traceback
import mutagen.mp3
import mutagen.id3
import io
import os
import time
from typing import Callable
from tqdm import tqdm
from nikoget import *
from nikoget.common import *
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

def download_audio(args, descriptor):
    '''
    Download a AudioDescriptor object

    It detects available meta information and patches them into the
    final audio file automatically, including the album cover.
    '''

    logger = colorlog.getLogger('nikoget')

    audio_tmpfile_path = os.path.join(args.output, 'tmp_' + descriptor.name)
    audio_fd = open(audio_tmpfile_path, 'wb')

    logger.info(f'Downloading audio "{descriptor.name}"')

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
    audio_file_path = os.path.join(args.output, descriptor.name + extension_name)

    pbar = tqdm(desc=descriptor.short_name, unit='MB', leave=False)

    # Show the progress of audio download task
    while audio_ctx.run_status == TaskStatus.running:
        pbar.total = round(audio_ctx.total_size / 1048576, 2)
        pbar.n = round(audio_ctx.downloaded_size / 1048576, 2)
        pbar.refresh()

    audio_fd.close()
    pbar.close()

    # Download the album cover
    if hasattr(descriptor, 'download_cover') and callable(descriptor.download_cover):
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
        cover_mine = None

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

    logger = colorlog.getLogger('nikoget')

    if audio_mime in ['audio/mp3', 'audio/mpeg', 'audio/mpeg3', 'audio/x-mpeg-3']:

        mp3 = mutagen.mp3.EasyMP3(audio_path)
        mp3.update(descriptor.as_easymp3_dict())
        mp3.save()

        mp3 = mutagen.id3.ID3(audio_path)

        if descriptor.lyrics is not None:
            open(os.path.join(args.output, descriptor.name) + '.lrc', 'w').write(descriptor.lyrics)
            mp3.add(mutagen.id3.USLT(encoding=3, desc='Lyrics', lang='eng', text=descriptor.lyrics))

        if cover is not None:
            mp3.add(mutagen.id3.APIC(encoding=3, desc='Cover', mime=cover_mime, data=cover))

        mp3.save()

    elif audio_mime in ['audio/mp4', 'video/mp4']:

        logger.warning(f'Unsupported audio format {audio_mime}. Meta info cannot be embedded')

    else:

        logger.warning(f'Unsupported audio format {audio_mime}. Meta info cannot be embedded')

def download(args):
    global SUBCOMMAND_ARGS
    SUBCOMMAND_ARGS = args

    logger = colorlog.getLogger('nikoget')

    for url in args.url:
        if target := match_url(url, PLUGINS):
            logger.debug(f'Matched URL: {url}')
            logger.debug('Using plugin \'{0}\'\r\n'.format(target.id()))
            try:
                descriptors = target.resolve_url(url)
                for i in descriptors:
                    if isinstance(i, AudioDescriptor):
                        download_audio(args, i)
            except Exception as err:
                logger.error('Unable to resolve url. Error detail:')
                if args.debug:
                    traceback.print_exception(err)
                else:
                    print(err)
        else:
            logger.warning(f'Unmatched URL: {url}')

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
    download_parser.add_argument('-o', '--output', help='Output folder', default='./')
    download_parser.set_defaults(func=download)

    args = parser.parse_args()

    # Debug logs
    if args.debug:
        logger.setLevel(colorlog.DEBUG)

    args.func(args)

if __name__ == '__main__':
    main()
