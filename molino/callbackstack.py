import functools


class CallbackStack:
    def __init__(self):
        self._stack = []

    def __call__(self, *args, **kwds):
        for callback in reversed(self._stack):
            if callback(*args, **kwds):
                return
        raise RuntimeError('Unhandled callback')

    def register(self, callback):
        self._stack.append(callback)

    def unregister(self, callback):
        self._stack.remove(callback)


class _CallbackProp:
    def __init__(self, f):
        self._f = f
        self.__doc__ = f.__doc__

    def __get__(self, obj, objtype):
        try:
            callbacks = obj._callbacks
        except AttributeError:
            callbacks = obj._callbacks = {}
        try:
            return callbacks[self._f.__name__]
        except KeyError:
            callback_stack = CallbackStack()
            callback_stack.register(functools.partial(self._f, obj))
            callbacks[self._f.__name__] = callback_stack
            return callback_stack

    def __set__(self, obj, value):
        raise AttributeError()

    def __delete__(self, obj):
        raise AttributeError()


def callback_stack(f):
    return _CallbackProp(f)
