import colorlog
from typing import List, Any

class SelectItem:
    def __init__(self, id: Any, display: str):
        self.display = display
        self.id = id

class Select:
    '''
    This class is used for select one or more items
    '''

    def __init__(self, items: List[SelectItem]):
        self._items = items

    @property
    def items(self):
        return self._items

    def select_one(self, filter=None):
        '''
        Select only one item from the list

        You can specify a filter which receives an argument and returns a bool value
        The received argument is current list item
        And returned bool value decides whether current item is available

        Unavailable items are hid automatically
        '''

        logger = colorlog.getLogger('nikoget')

        items = list(__builtins__['filter'](filter, self.items))

        if len(items) == 0:
            return

        number_bits = len(str(len(items) - 1))
        for i in range(len(items)):
            print('{}{}  {}'.format(i, ' ' * (number_bits - len(str(i))), items[i].display))

        print('Select one from above items')

        while True:
            try:
                user_input = int(input('Type a number: '))

                if user_input >= len(items) or user_input < 0:
                    print('The number is out of range. Please try again.')
                    continue

                else:
                    return items[user_input].id

                break

            except ValueError:
                print('Sorry, what you typed is not a correct number. Please try again.')
                continue

            except EOFError:
                logger.debug('User aborted (EOFError)')
                return None

            except KeyboardInterrupt:
                logger.debug('User aborted (KeyboardInterrupt)')
                return None

    def select_multi(self, limit=0, use_curses=True):
        '''
        Select multiple items

        :param: limit The limit of number of items
        :param: use_curses Whether use curses automatically if it is available
        '''

        

