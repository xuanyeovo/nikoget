from typing import List, Callable, Optional, Any, Set
from enum import Enum
from threading import Lock, Thread
from io import BytesIO
from abc import ABC, abstractmethod
from mutagen.id3 import USLT, ID3

# Default chunk size for streaming download task
STREAM_CHUNK_SIZE = 2048

def _insert_if_sth(target_dict: dict, key, value):
    if not (value is None or (value is list and len(value) == 0)):
        if value is list:
            target_dict[key] = value
        else:
            target_dict[key] = [value]

class BrokenError(Exception):
    '''
    Thown when a object was broken by another exception

    A property named 'caused_by' can trace back to the origin of exception
    '''

    def __init__(self, caused_by: Exception):
        super().__init__('Broken operation')
        self._caused_by = caused_by

    @property
    def caused_by(self):
        return self._caused_by

    def __str__(self):
        return f'Broken operation caused by {self._caused_by}'

class ResolveError(Exception):
    def __init__(self, why: str):
        self._why = why

    @property
    def why(self)-> str:
        return self._why

    def __str__(self):
        return self._why

class NetworkError(Exception):
    def __init__(self, why: str):
        self._why = why

    @property
    def why(self)-> str:
        return self._why

    def __str__(self):
        return self._why

class TaskStatus(Enum):
    '''
    Signs the current status of a task

    pending - The task is ready but not running
    running - The task is currently running
    finished - The task successfully finished
    error_occurred - The task ended with an error
    '''

    pending = 0
    running = 1
    finished = 2
    error_occurred = 3

class MediaType(Enum):
    audio = 0
    lyric = 1
    video = 2
    picture = 3

class DownloadContext:
    '''
    Context for a download task
    Download work is doing in another thread

    The thread's running status can be traced by accessing the property 'run_status'
    Property 'total_size' and 'downloaded_size' are also useful when showing a progress bar

    Special circumstances:
        - 'total_size' being 0 means that the data has a unknown size
    '''

    def __init__(self, bootstrap: Callable[Any, Optional[Exception]]):
        '''
        Bootstrap function should download the
        data and write them into DownloadContext.output

        If there are, it should also update the
        properties 'total_size' and 'download_size' of DownloadContext

        Parameters:
          bootstrap - a function receives a DownloadContext object
        '''
        self._bootstrap = bootstrap
        self._run_status = TaskStatus.pending
        self.lock = Lock()
        self._error = None
        self.mime = None
        self.headers_ready = False
        self.total_size = 0
        self.downloaded_size = 0

    def run(self)-> Optional[Thread]:
        '''
        Start another thread to download data

        If the property 'run_status' is not `TaskStatus.pending`,
        this method does nothing
        '''

        def bootstrap():
            self._run_status = TaskStatus.running

            try:
                result = self._bootstrap(self)
            except Exception as err:
                result = err

            if not result is None:
                self.lock.acquire()
                self._run_status = TaskStatus.error_occurred
                self._error = result
                self.lock.release()
            else:
                self._run_status = TaskStatus.finished

        if self._run_status == TaskStatus.pending:
            thr = Thread(target=bootstrap, name='Download worker thread')
            thr.start()
            return thr
        else:
            return

    @property
    def run_status(self)-> TaskStatus:
        self.lock.acquire()
        temp = self._run_status
        self.lock.release()
        return temp

    @property
    def error(self)-> Optional[Exception]:
        self.lock.acquire()
        temp = self._error
        self.lock.release()
        return temp

class ThinAudioDescriptor(ABC):
    def __init__(self):
        self.title = ''
        self.artist = []
        self.album = ''

    @property
    def artist_str(self):
        return '/'.join(self.artist)

    @property
    def name(self):
        return '{0} - {1}'.format(self.artist_str.replace('/', ', '), self.title)

    @abstractmethod
    def to_full(self):
        '''
        Convert this thin descriptor into normal descriptor.
        '''
        pass

class AudioDescriptor(ABC):
    def __init__(self):
        self.title = ''
        self.artist = []
        self.album_artist = []
        self.album = ''
        self.disc_number = None
        self.date = None
        self.track_number = '01'
        self.track_number_total = None
        self.comment = None
        self.lyrics = None

    def as_easymp3_dict(self):
        temp_dict = {
            'title': [self.title],
            'album': [self.album],
            'artist': [self.artist_str],
            'tracknumber': [self.track_number],
        }
        _insert_if_sth(temp_dict, 'albumartist', self.album_artist_str)
        _insert_if_sth(temp_dict, 'discnumber', self.disc_number)
        _insert_if_sth(temp_dict, 'comment', self.comment)
        _insert_if_sth(temp_dict, 'date', self.date)
        if extra := self.easymp3_extra():
            temp_dict.update(extra)
        return temp_dict

    def as_mp4_dict(self):
        temp_dict = {
            '©nam': [self.title],
            '©ART': [self.artist_str],
            '©alb': [self.album],
            'trkn': [(int(self.track_number), int(self.track_number_total) if self.track_number_total is not None else 0)],
        }
        _insert_if_sth(temp_dict, 'aART', self.album_artist_str)
        _insert_if_sth(temp_dict, 'disk', self.disc_number)
        _insert_if_sth(temp_dict, '©cmt', self.comment)
        _insert_if_sth(temp_dict, '©lyr', self.lyrics)
        _insert_if_sth(temp_dict, '©day', self.date)
        if 'disk' in temp_dict:
            temp_dict['disk'] = (int(temp_disk['disk']), 0)
        if extra := self.mp4_extra():
            temp_dict.update(extra)
        return temp_dict

    def patch_id3(self, id3_obj):
        if self.lyrics is not None:
            lyrics_frame = USLT(encoding=3, desc='', lang='eng', text=self.lyrics)
            id3_obj.add(lyrics_frame)

        self.patch_id3_extra(id3_obj)

    @property
    def artist_str(self):
        return '/'.join(self.artist)

    @property
    def album_artist_str(self):
        return '/'.join(self.album_artist)

    @property
    def name(self):
        return '{0} - {1}'.format(self.artist_str.replace('/', ', '), self.title)

    @property
    def short_name(self):
        return self.title

    @abstractmethod
    def easymp3_extra(self):
        pass

    @abstractmethod
    def mp4_extra(self):
        pass

    @abstractmethod
    def patch_id3_extra(self, id3_obj):
        pass

    @abstractmethod
    def download(self, output: BytesIO)-> DownloadContext:
        pass

class VideoDescriptor:
    pass



class Plugin(ABC):
    @abstractmethod
    def match_url(self, url: str)-> bool:
        '''
        Matchs the provided url

        If return True, the request will be handed over to the current plugin for processing
        If return False, the request will match the next plugin
        '''
        pass

    @abstractmethod
    def resolve_url(self, url: str):
        pass

    """
    @abstractmethod
    def media_types(self, url: str)-> Set[MediaType]:
        # TODO
        '''
        Return the media types found in that page

        (Planning)
        '''
    """

    @property
    @abstractmethod
    def id(self)-> str:
        pass

    @property
    @abstractmethod
    def version(self)-> str:
        pass
