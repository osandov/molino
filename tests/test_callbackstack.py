import unittest
from unittest.mock import MagicMock

from molino.callbackstack import CallbackStack, callback_stack


class TestCallbackStack(unittest.TestCase):
    def setUp(self):
        self.stack = CallbackStack()

    def test_empty(self):
        self.assertRaises(RuntimeError, self.stack)

    def test_single(self):
        callback = MagicMock(return_value=True)
        self.stack.register(callback)
        self.stack(666)
        callback.assert_called_once_with(666)
        self.stack.unregister(callback)
        self.assertRaises(RuntimeError, self.stack)

    def test_single_unhandled(self):
        callback = MagicMock(return_value=False)
        self.stack.register(callback)
        self.assertRaises(RuntimeError, self.stack, 666)
        callback.assert_called_once_with(666)
        self.stack.unregister(callback)
        self.assertRaises(RuntimeError, self.stack)

    def test_multiple(self):
        callback1 = MagicMock(return_value=True)
        callback2 = MagicMock(return_value=False)
        callback3 = MagicMock(return_value=True)

        self.stack.register(callback1)
        self.stack.register(callback2)
        self.stack(666)
        callback1.assert_called_once_with(666)
        callback1.reset_mock()
        callback2.assert_called_once_with(666)
        callback2.reset_mock()

        self.stack.register(callback3)
        self.stack(666)
        callback1.assert_not_called()
        callback1.reset_mock()
        callback2.assert_not_called()
        callback2.reset_mock()
        callback3.assert_called_once_with(666)

        self.stack.unregister(callback1)
        self.stack.unregister(callback3)
        self.assertRaises(RuntimeError, self.stack, 666)
        callback2.assert_called_once_with(666)

        self.stack.unregister(callback2)
        self.assertRaises(RuntimeError, self.stack)


class TestCallbackProp(unittest.TestCase):
    class TestClass:
        @callback_stack
        def handled(self, x):
            return True

        @callback_stack
        def unhandled(self, x):
            return False

    def setUp(self):
        self.test = TestCallbackProp.TestClass()

    def test_handled(self):
        callback = MagicMock(return_value=True)
        self.test.handled(666)
        self.test.handled.register(callback)
        self.test.handled(666)
        callback.assert_called_once_with(666)

    def test_unhandled(self):
        callback = MagicMock(return_value=True)
        self.assertRaises(RuntimeError, self.test.unhandled, 666)
        self.test.unhandled.register(callback)
        self.test.unhandled(666)
        callback.assert_called_once_with(666)

    def test_attribute(self):
        with self.assertRaises(AttributeError):
            self.test.handled = lambda x: True
        with self.assertRaises(AttributeError):
            self.test.unhandled = lambda x: False
        with self.assertRaises(AttributeError):
            del self.test.handled
        with self.assertRaises(AttributeError):
            del self.test.unhandled
