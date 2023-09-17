from nikoget.common import *
from typing import Set
import mutagen.id3
import requests
import urllib.parse
import re
import time
import json
import colorlog

_ID = 'org.xuanyeovo.ncm'
_VERSION = '0.0.1(20230908)'

DATA_EXTRACTOR = re.compile('window\\.REDUX_STATE = ({.*});')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Linux; Android 13; 23054RA19C Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.5563.116 Mobile Safari/537.36'}

def _get_album(id):
    logger = colorlog.getLogger('nikoget')
    logger.debug(f'Fetching info about album {id}')

    page_req = requests.get(f'https://y.music.163.com/m/album?id={id}', headers=HEADERS)

    result = {}

    if jdata := DATA_EXTRACTOR.search(page_req.text):
        info = json.loads(jdata.group(1))
        album = info['Album']['album']

        def extractor(i):
            return {
                'id': i['id'],
                'name': i['songName'],
            }

        result['name'] = album['name']
        result['publish_time'] = album['publishTime']
        result['songs'] = list(map(extractor, album['songs']))
        result['artist'] = '/'.join(list(map(lambda x:x['name'], album['artists'])))
        result['publish_time'] = time.strftime('%Y/%m/%d', time.localtime(album['publishTime']))
    else:
        raise ResolveError('Cannot obtain album data from the page')

    return result

def _get_lyrics(id):
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
        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.netloc in ['music.163.com', 'y.music.163.com']:
            path = parsed_url.path.split('/')
            if len(path) < 2:
                raise ResolveError('Incompleted URL path')
            else:
                del(path[0])

            if path[0] == 'm':
                # Mobile share page
                del(path[0])
                if len(path) == 1 and path[0] == 'song':
                    query = urllib.parse.parse_qs(parsed_url.query)
                    if id := query.get('id')[0]:
                        return [NcmAudio(id)]
                    else:
                        raise ResolveError('Query field \'id\' is missing')
                else:
                    raise ResolveError('Incompleted mobile share URL')
            else:
                raise ResolveError('Unsupported URL path')

    def id(self)-> str:
        return _ID

    def version(self)-> str:
        return _VERSION

class NcmAudio(AudioDescriptor):
    def __init__(self, id: str):
        super().__init__()

        self._id = id

        logger = colorlog.getLogger('nikoget')
        logger.debug(f'Fetching audio info about {id}')

        page_req = requests.get(f'https://music.163.com/m/song?id={self.ncm_id}', headers=HEADERS)
        if result := DATA_EXTRACTOR.search(page_req.text):
            data = json.loads(result.group(1))
            self._raw_data = data
            info = data['Song']
            self.title = info['name']
            self.album = info['al']['name']
            self.artist = ['/'.join(list(map(lambda x:x['name'], info['ar'])))]
            self.track_number = '01'
            self._cover_url = info['al']['picUrl']
            album_info = _get_album(info['al']['id'])
            for i in range(len(album_info['songs'])):
                if id == album_info['songs'][i]['id']:
                    self.track_number = '{:02}'.format(i)
                    break

            self.album_artist = [album_info['artist']]
            self.date = album_info['publish_time']
            self.lyrics = _get_lyrics(id)
        else:
            raise ResolveError('Cannot obtain audio meta info from the page')

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

    def easymp3_extra(self):
        return {}

    def mp4_extra(self):
        return {
            'netease_id': [f'{self.ncm_id}']
        }

    def patch_id3_extra(self, id3_obj):
        nid = mutagen.id3.TXXX(desc='NETEASE-ID', text=self.ncm_id)

        id3_obj.add(nid)

plugin = NcmPlugin()
