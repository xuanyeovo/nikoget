from .common import BrokenError, Plugin
from typing import Optional
import os
import importlib.util

class PluginLoader:
    '''
    Find and load nikoget plugins.
    This iterates all file under the directory of 'nikoget.plugins' and load them
    '''

    def __init__(self, extra_plugins=[], directory=os.path.join(os.path.dirname(__file__), 'plugins')):
        self._plugin_files = os.listdir(directory)
        self._plugins = extra_plugins
        self._broken = None

        for module_name in self._plugin_files:
            if module_name.startswith('__'):
                continue

            try:
                module_spec = importlib.util.spec_from_file_location(os.path.splitext(module_name)[0], os.path.join(directory, module_name))
                module = importlib.util.module_from_spec(module_spec)
                module_spec.loader.exec_module(module)
                if 'plugin' in module.__dict__:
                    self._plugins.append(module.plugin)
            except Exception as exc:
                self._broken = BrokenError(exc)
                break

            self._plugins.append(module)

    def __iter__(self):
        if self.is_broken:
            raise self._broken
        return self._plugins.__iter__()

    @property
    def is_broken(self):
        return not self._broken is None

def match_url(url: str, plugins: PluginLoader)-> Optional[Plugin]:
    for plugin in plugins:
        if plugin.match_url(url):
            return plugin
    return


