from typing import Set
import requests
import re
import time
import json
import urllib.parse

_ID = 'org.xuanyeovo.ncm'
_VERSION = '0.0.2(20231005)'

DATA_EXTRACTOR = re.compile('window\\.REDUX_STATE = ({.*});')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Linux; Android 13; 23054RA19C Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.5563.116 Mobile Safari/537.36'}

ALBUM_CACHE = {}
PLAYLIST_CACHE = {}

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print('[Error] Too few arguments')
        exit(1)
    if sys.argv[1] == 'raw_info':
        req = requests.get(sys.argv[2], headers=HEADERS)
        if result := DATA_EXTRACTOR.search(req.text):
            jdata = json.loads(result.group(1))
            print(json.dumps(jdata, indent=2, sort_keys=True, ensure_ascii=False))
    exit(0)

from nikoget.common import *
import mutagen.id3
import colorlog

def _get_album(id):
    logger = colorlog.getLogger('nikoget')
    logger.debug(f'Fetching info about album {id}')

    if id in ALBUM_CACHE:
        return ALBUM_CACHE[id]

    result = { 'is_empty': False }

    page_req = requests.get(f'https://y.music.163.com/m/album?id={id}', headers=HEADERS)

    if jdata := DATA_EXTRACTOR.search(page_req.text):
        info = json.loads(jdata.group(1))

        if 'album' not in info['Album']:
            #raise ResolveError('Incorrect album identifier')
            logger.warn(f'No album found')
            result['is_empty'] = True
            return result

        album = info['Album']['album']

        def extractor(i):
            return {
                'title': i['songName'],
                'album': i['albumName'],
                'id': i['id'],
                'artist': i['singerName'].split(' / '),
            }

        result['name'] = album['name']
        result['publish_time'] = album['publishTime']
        result['songs'] = list(map(extractor, info['Album']['songs']))
        result['artist'] = '/'.join(list(map(lambda x:x['name'], album['artists'])))
        result['publish_time'] = time.strftime('%Y/%m/%d', time.localtime(album['publishTime'] / 1000))
    else:
        raise ResolveError('Cannot obtain album data from the page')

    ALBUM_CACHE[id] = result

    return result

def _get_playlist(id):
    logger = colorlog.getLogger('nikoget')
    logger.debug(f'Fetching info about playlist {id}')

    if id in PLAYLIST_CACHE:
        return PLAYLIST_CACHE[id]

    result = {}

    page_req = requests.get(f'https://y.music.163.com/m/playlist?id={id}', headers=HEADERS)

    if jdata := DATA_EXTRACTOR.search(page_req.text):
        info = json.loads(jdata.group(1))

        pl = info['Playlist']

        def extractor(i):
            return {
                'title': i['songName'],
                'album': i['albumName'],
                'id': i['id'],
                'artist': i['singerName'].split(' / '),
            }

        result['songs'] = list(map(extractor, pl['data']))
        result['name'] = pl['info']['name']
        result['create_time'] = pl['info']['createTime']
        result['creator_name'] = pl['info']['creator']['nickname']

    else:
        raise ResolveError('Cannot obtain playlist info from the page')

    PLAYLIST_CACHE['id'] = result

    return result

def _get_lyrics(id):
    '''
    Obtain the corresponding lyrics by ID
    '''
    logger = colorlog.getLogger('nikoget')
    logger.debug(f'Fetching lyrics of {id}')

    lyrics_req = requests.get(f'https://music.163.com/api/song/lyric?id={id}&lv=1&kv=1&tv=-1')
    j = json.loads(lyrics_req.text)
    if j.get('pureMusic') == True:
        return "[00:00.00] 纯音乐"
    else:
        result = j['lrc']['lyric']

    if j['tlyric']['lyric'] != '':
        result += '\r\n'
        result += j['tlyric']['lyric']

    return result

def _ret_or_default(val, default):
    if not val is None:
        return val
    else:
        return default

class NcmPlugin(Plugin):
    def __init__(self):
        pass

    def match_url(self, url: str)-> bool:
        parsed_url = urllib.parse.urlparse(url)
        return parsed_url.netloc in ['y.music.163.com', 'music.163.com']

    def resolve_url(self, url: str):
        parsed_url = urllib.parse.urlparse(url.replace('#', '%23'))
        if parsed_url.netloc in ['music.163.com', 'y.music.163.com']:
            path = parsed_url.path.split('/')
            if len(path) < 2:
                raise ResolveError('Incompleted URL path')
            else:
                del(path[0])

            if path[0] in ['m', '%23']:
                del(path[0])

            query = urllib.parse.parse_qs(parsed_url.query)
            if path[0] == 'song':
                if len(path) == 2:
                    return [NcmAudio.from_id(path[1])]
                elif len(path) == 1 and 'id' in query:
                    return [NcmAudio.from_id(query['id'][0])]

            elif path[0] == 'album':
                if len(path) == 2:
                    return list(map(lambda x:NcmThinAudio(**x), _get_album(path[1])['songs']))
                elif len(path) == 1 and 'id' in query:
                    return list(map(lambda x:NcmThinAudio(**x), _get_album(query['id'][0])['songs']))

            elif path[0] == 'playlist':
                if len(path) == 2:
                    return list(map(lambda x:NcmThinAudio(**x), _get_playlist(path[1])['songs']))
                elif len(path) == 1 and 'id' in query:
                    return list(map(lambda x:NcmThinAudio(**x), _get_playlist(query['id'][0])['songs']))

            else:
                raise ResolveError('Unsupported type')

            raise ResolveError('Identifier is missing')


    def id(self)-> str:
        return _ID

    def version(self)-> str:
        return _VERSION

class NcmThinAudio(ThinAudioDescriptor):
    def __init__(self, id, title, artist, album):
        super().__init__()

        self.title = title
        self.artist = artist
        self.album = album
        self.ncm_id = id

    def to_full(self):
        return NcmAudio.from_id(self.ncm_id)

class NcmAudio(AudioDescriptor):
    def __init__(self):
        super().__init__()

    def from_id(id):
        self = NcmAudio()

        self._id = id

        logger = colorlog.getLogger('nikoget')
        logger.debug(f'Fetching audio info about {id}')

        page_req = requests.get(f'https://music.163.com/m/song?id={self.ncm_id}', headers=HEADERS)
        if result := DATA_EXTRACTOR.search(page_req.text):
            data = json.loads(result.group(1))
            self._raw_data = data
            info = data['Song']

            if info == {}:
                raise ResolveError('Incorrect song identifier')

            self.title = info['name']
            self.album = info['al']['name']
            self.artist = ['/'.join(list(map(lambda x:x['name'], info['ar'])))]
            self.track_number = '01'
            self._cover_url = info['al']['picUrl']
            album_info = _get_album(info['al']['id'])
            if not album_info.get('is_empty'):
                found_trkn = False
                for i in range(len(album_info['songs'])):
                    if str(album_info['songs'][i]['id']) == id:
                        self.track_number = '{:02}'.format(i + 1)
                        found_trkn = True
                        break

                if not found_trkn:
                    logger.warning(f'could not get track number of "{self.name}"')

                self.track_number_total = '{:02}'.format(len(album_info['songs']))
                self.album_artist = [album_info['artist']]
                self.date = album_info['publish_time']
            self.lyrics = _get_lyrics(id)
        else:
            raise ResolveError('Cannot obtain audio meta info from the page')

        return self

    @property
    def ncm_id(self):
        return self._id

    @property
    def ncm_raw_data(self):
        return self._raw_data

    @property
    def ncm_download_url(self):
        return f'https://music.163.com/song/media/outer/url?id={self.ncm_id}.mp3'

    @property
    def ncm_cover_url(self):
        return self._cover_url

    def download_cover(self, output):
        def download_cover(ctx):
            url = self.ncm_cover_url

            logger = colorlog.getLogger('nikoget')
            logger.debug(f'Downloading cover from {url}')

            req = requests.get(url, headers=HEADERS, stream=True)
            ctx.total_size = int(req.headers['Content-Length'])
            ctx.mime = req.headers.get('Content-Type').split(';')[0]
            ctx.downloaded_size = 0

            ctx.headers_ready = True

            for chunk in req.iter_content(chunk_size=STREAM_CHUNK_SIZE):
                ctx.downloaded_size += len(chunk)
                output.write(chunk)

            req.close()

        return DownloadContext(download_cover)

    def download(self, output):
        def download(ctx):
            url = self.ncm_download_url

            logger = colorlog.getLogger('nikoget')
            logger.debug(f'Downloading audio from {url}')

            req = requests.get(url, headers=HEADERS, stream=True)
            ctx.total_size = int(req.headers['Content-Length'])
            ctx.mime = req.headers.get('Content-Type').split(';')[0]
            ctx.downloaded_size = 0

            ctx.headers_ready = True

            for chunk in req.iter_content(chunk_size=STREAM_CHUNK_SIZE):
                ctx.downloaded_size += len(chunk)
                output.write(chunk)

            req.close()

        return DownloadContext(download)

    def flac_extra(self):
        return {
            'netease_id': [f'{self.ncm_id}']
        }

    def mp4_extra(self):
        return {
            'netease_id': [f'{self.ncm_id}']
        }

    def patch_id3_extra(self, id3_obj):
        nid = mutagen.id3.TXXX(desc='NETEASE-ID', text=self.ncm_id)

        id3_obj.add(nid)

plugin = NcmPlugin()

