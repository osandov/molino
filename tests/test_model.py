import sqlite3
import unittest
from unittest.mock import MagicMock

from molino.model import *
from molino.imap.parser import *


class TestMessage(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.model = Model(self.db)

    def test_id(self):
        message = Message(self.model, 1337)
        self.assertEqual(message.id, 1337)

    def test_no_envelope(self):
        message = Message(self.model, 1337)
        self.assertEqual(message.envelope, None)
        self.assertEqual(message.subject(), None)
        self.assertEqual(message.from_(), None)
        self.assertEqual(message.from_(True), None)
        self.assertEqual(message.to(), None)
        self.assertEqual(message.to(True), None)
        self.assertEqual(message.cc(), None)
        self.assertEqual(message.cc(True), None)
        self.assertEqual(message.bcc(), None)
        self.assertEqual(message.bcc(True), None)

    def test_empty_envelope(self):
        callback = MagicMock(return_value=False)
        self.model.on_message_update.register(callback)
        message = Message(self.model, 1337)
        envelope = Envelope(None, None, None, None, None, None, None, None, None, None)
        message.envelope = envelope
        callback.assert_called_once_with(message, 'envelope')

        self.assertEqual(message.envelope, envelope)
        self.assertEqual(message.subject(), None)
        self.assertEqual(message.from_(), None)
        self.assertEqual(message.from_(True), None)
        self.assertEqual(message.to(), None)
        self.assertEqual(message.to(True), None)
        self.assertEqual(message.cc(), None)
        self.assertEqual(message.cc(True), None)
        self.assertEqual(message.bcc(), None)
        self.assertEqual(message.bcc(True), None)

    def test_envelope(self):
        envelope = Envelope(
            datetime.datetime(2002, 10, 31, 8, 0,
                              tzinfo=datetime.timezone(datetime.timedelta(-1, 68400))),
            b"Re: Halloween",
            [Address(b'Example User 1', None, b'example1', b'example.com')],
            None,
            [Address(b'Example User 1', None, b'example1', b'example.com')],
            [Address(None, None, b'example2', b'example.com')],
            [Address(b'=?utf-8?q?Example_=C3=9Cser_3?=', None, b'example3', b'example.com')],
            [Address(b'Example User 4', None, b'example4', b'example.com'),
             Address(b'Example User 5', None, b'example5', b'example.com')],
            b'<1234@local.machine.example>', b'<3456@example.net>',
        )
        message = Message(self.model, 1337)
        message.envelope = envelope

        self.assertEqual(message.envelope, envelope)
        self.assertEqual(message.subject(), 'Re: Halloween')
        self.assertEqual(message.from_(), ['"Example User 1" <example1@example.com>'])
        self.assertEqual(message.from_(True), ['Example User 1'])
        self.assertEqual(message.to(), ['example2@example.com'])
        self.assertEqual(message.to(True), ['example2@example.com'])
        self.assertEqual(message.cc(), ['"Example Üser 3" <example3@example.com>'])
        self.assertEqual(message.cc(True), ['Example Üser 3'])
        self.assertEqual(message.bcc(), ['"Example User 4" <example4@example.com>',
                                         '"Example User 5" <example5@example.com>'])
        self.assertEqual(message.bcc(True), ['Example User 4', 'Example User 5'])

    def test_malformed_envelope(self):
        envelope = Envelope(
            datetime.datetime(2002, 10, 31, 8, 0,
                              tzinfo=datetime.timezone(datetime.timedelta(-1, 68400))),
            b'=?iso-8859-1?=A1Hola,_se=F1or!?=',
            [Address(b'Example Use\xf2', None, b'example', b'example.com')],
            None,
            None,
            [Address(b'=?utf-8?q?Example_=C3=28ser?=', None, b'example', b'example.com')],
            None, None,
            b'<1234@local.machine.example>', b'<3456@example.net>',
        )
        message = Message(self.model, 1337)
        message.envelope = envelope

        self.assertEqual(message.envelope, envelope)
        self.assertEqual(message.subject(), '=?iso-8859-1?=A1Hola,_se=F1or!?=')
        self.assertEqual(message.from_(), ['"Example Use\\\\xf2" <example@example.com>'])
        self.assertEqual(message.from_(True), ['Example Use\\xf2'])
        self.assertEqual(message.to(), ['"Example \\\\xc3(ser" <example@example.com>'])
        self.assertEqual(message.to(True), ['Example \\xc3(ser'])

    def test_bodystructure(self):
        callback = MagicMock(return_value=False)
        self.model.on_message_update.register(callback)
        message = Message(self.model, 1337)
        body = TextBody('text', 'plain', {'charset': 'us-ascii'}, None, None,
                        '7bit', 252, 11, None, None, None, None, [])
        message.bodystructure = body
        callback.assert_called_once_with(message, 'bodystructure')
        self.assertEqual(message.bodystructure, body)

    def test_body_sections(self):
        callback = MagicMock(return_value=False)
        self.model.on_message_update.register(callback)
        message = Message(self.model, 1337)
        self.assertRaises(KeyError, message.get_body_section, '')
        self.assertFalse(message.have_body_section(''))
        # TODO: non-None origin
        message.add_body_sections({'': (b'asdf', None)})
        callback.assert_called_once_with(message, 'body')
        self.assertEqual(message.get_body_section(''), b'asdf')
        self.assertTrue(message.have_body_section(''))

    def test_flags(self):
        callback = MagicMock(return_value=False)
        self.model.on_message_update.register(callback)
        message = Message(self.model, 1337)
        self.assertEqual(message.flags, None)
        message.flags = {'\\Seen'}
        callback.assert_called_once_with(message, 'flags')
        self.assertEqual(message.flags, {'\\Seen'})


class TestMailbox(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.model = Model(self.db)

    def test_name(self):
        mailbox = Mailbox(self.model, b'INBOX', ord('/'), set())
        self.assertEqual(mailbox.name, b'INBOX')
        self.assertEqual(mailbox.name_decoded, 'Inbox')

        # Modified UTF-7
        mailbox = Mailbox(self.model, b'P&AOk-rez', ord('/'), set())
        self.assertEqual(mailbox.name, b'P&AOk-rez')
        self.assertEqual(mailbox.name_decoded, 'Pérez')

        # UTF-8 fallback
        mailbox = Mailbox(self.model, b'P\xc3\xa9rez', ord('/'), set())
        self.assertEqual(mailbox.name, b'P\xc3\xa9rez')
        self.assertEqual(mailbox.name_decoded, 'Pérez')

        # Invalid UTF-8
        mailbox = Mailbox(self.model, b'P\xc3\x28rez', ord('/'), set())
        self.assertEqual(mailbox.name, b'P\xc3\x28rez')
        self.assertEqual(mailbox.name_decoded, 'P\\xc3(rez')

    def test_delimiter(self):
        callback = MagicMock(return_value=False)
        self.model.on_mailbox_update.register(callback)
        mailbox = Mailbox(self.model, b'INBOX', None, set())
        self.assertEqual(mailbox.delimiter, None)
        mailbox.delimiter = ord('/')
        callback.assert_called_once_with(mailbox, 'delimiter')

    def test_attributes(self):
        callback = MagicMock(return_value=False)
        self.model.on_mailbox_update.register(callback)
        mailbox = Mailbox(self.model, b'INBOX', None, set())
        self.assertEqual(mailbox.attributes, set())
        self.assertTrue(mailbox.can_select())

        mailbox.attributes = {'\\Noinferiors', '\\Marked'}
        callback.assert_called_once_with(mailbox, 'attributes')
        self.assertEqual(mailbox.attributes, {'\\Noinferiors', '\\Marked'})
        self.assertTrue(mailbox.can_select())

        mailbox.attributes = {'\\Noselect'}
        self.assertEqual(mailbox.attributes, {'\\Noselect'})
        self.assertFalse(mailbox.can_select())

        mailbox.attributes = {'\\NonExistent'}
        self.assertEqual(mailbox.attributes, {'\\NonExistent'})
        self.assertFalse(mailbox.can_select())

    def test_exists(self):
        callback = MagicMock(return_value=False)
        self.model.on_mailbox_update.register(callback)
        mailbox = Mailbox(self.model, b'INBOX', None, set())
        self.assertEqual(mailbox.exists, None)
        mailbox.exists = 5
        callback.assert_called_once_with(mailbox, 'exists')
        self.assertEqual(mailbox.exists, 5)

    def test_unseen(self):
        callback = MagicMock(return_value=False)
        self.model.on_mailbox_update.register(callback)
        mailbox = Mailbox(self.model, b'INBOX', None, set())

        mailbox.set_num_unseen(1)
        callback.assert_called_once_with(mailbox, 'unseen')
        callback.reset_mock()
        self.assertEqual(mailbox.num_unseen(), 1)

        mailbox.set_unseen({7, 11})
        callback.assert_called_once_with(mailbox, 'unseen')
        callback.reset_mock()
        self.assertEqual(mailbox.num_unseen(), 2)

        mailbox.add_unseen(8)
        callback.assert_called_once_with(mailbox, 'unseen')
        callback.reset_mock()
        self.assertEqual(mailbox.num_unseen(), 3)

        mailbox.remove_unseen(8)
        callback.assert_called_once_with(mailbox, 'unseen')
        callback.reset_mock()
        self.assertEqual(mailbox.num_unseen(), 2)

        mailbox.add_unseen(7)
        callback.assert_not_called()
        callback.reset_mock()
        self.assertEqual(mailbox.num_unseen(), 2)

        mailbox.remove_unseen(8)
        callback.assert_not_called()
        callback.reset_mock()
        self.assertEqual(mailbox.num_unseen(), 2)

        mailbox.set_num_unseen(10)
        callback.assert_called_once_with(mailbox, 'unseen')
        callback.reset_mock()
        self.assertEqual(mailbox.num_unseen(), 10)

        mailbox.remove_unseen(11)
        callback.assert_called_once_with(mailbox, 'unseen')
        callback.reset_mock()
        self.assertEqual(mailbox.num_unseen(), 1)

    def test_recent(self):
        callback = MagicMock(return_value=False)
        self.model.on_mailbox_update.register(callback)
        mailbox = Mailbox(self.model, b'INBOX', None, set())
        self.assertEqual(mailbox.recent, None)
        mailbox.recent = 5
        callback.assert_called_once_with(mailbox, 'recent')
        self.assertEqual(mailbox.recent, 5)

    def test_flags(self):
        callback = MagicMock(return_value=False)
        self.model.on_mailbox_update.register(callback)
        mailbox = Mailbox(self.model, b'INBOX', None, set())
        self.assertEqual(mailbox.flags, None)
        mailbox.flags = {'\\Answered', '\\Flagged', '\\Deleted', '\\Seen',
                         '\\Draft'}
        callback.assert_called_once_with(mailbox, 'flags')
        self.assertEqual(mailbox.flags, {'\\Answered', '\\Flagged',
                                         '\\Deleted', '\\Seen', '\\Draft'})

    def test_uids(self):
        mailbox = Mailbox(self.model, b'INBOX', None, set())
        self.assertEqual(mailbox.uids, [])
        mailbox.uids = [None, 1, 3, 10]
        self.assertEqual(mailbox.uids, [None, 1, 3, 10])

    def test_messages(self):
        add_callback = MagicMock(return_value=False)
        delete_callback = MagicMock(return_value=False)
        self.model.on_message_add.register(add_callback)
        self.model.on_message_delete.register(delete_callback)
        message1 = Message(self.model, 1337)
        message2 = Message(self.model, 666)
        mailbox = Mailbox(self.model, b'INBOX', None, set())

        self.assertFalse(mailbox.contains_message(7))
        self.assertFalse(mailbox.contains_message(11))
        self.assertEqual(dict(mailbox.messages()), {})

        mailbox.add_message(7, message1)
        add_callback.assert_called_once_with(mailbox, 7, message1)
        add_callback.reset_mock()
        self.assertTrue(mailbox.contains_message(7))
        self.assertFalse(mailbox.contains_message(11))
        self.assertEqual(dict(mailbox.messages()), {7: message1})

        mailbox.add_message(11, message2)
        add_callback.assert_called_once_with(mailbox, 11, message2)
        add_callback.reset_mock()
        self.assertTrue(mailbox.contains_message(7))
        self.assertTrue(mailbox.contains_message(11))
        self.assertEqual(dict(mailbox.messages()), {7: message1, 11: message2})
        self.assertEqual(mailbox.get_message(7), message1)
        self.assertEqual(mailbox.get_message(11), message2)

        mailbox.delete_message(7)
        delete_callback.assert_called_once_with(mailbox, 7, message1)
        delete_callback.reset_mock()
        self.assertFalse(mailbox.contains_message(7))
        self.assertTrue(mailbox.contains_message(11))
        self.assertEqual(dict(mailbox.messages()), {11: message2})

        mailbox.delete_message(11)
        delete_callback.assert_called_once_with(mailbox, 11, message2)
        delete_callback.reset_mock()
        self.assertFalse(mailbox.contains_message(7))
        self.assertFalse(mailbox.contains_message(11))
        self.assertEqual(dict(mailbox.messages()), {})

        self.assertRaises(KeyError, mailbox.get_message, 7)


class TestModel(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.model = Model(self.db)

    def test_init(self):
        self.assertEqual({mbx.name for mbx in self.model.mailboxes()}, {b'INBOX'})
        inbox = self.model.get_mailbox(b'INBOX')
        self.assertEqual(inbox.delimiter, ord('/'))
        self.assertEqual(inbox.attributes, set())
        self.assertRaises(KeyError, self.model.get_mailbox, b'Foo')

    def test_mailboxes(self):
        add_callback = MagicMock(return_value=False)
        delete_callback = MagicMock(return_value=False)
        self.model.on_mailboxes_add.register(add_callback)
        self.model.on_mailboxes_delete.register(delete_callback)

        mailbox1 = Mailbox(self.model, b'Foo', ord('/'), set())
        mailbox2 = Mailbox(self.model, b'Bar', ord('/'), set())

        self.model.add_mailbox(mailbox1)
        add_callback.assert_called_once_with(mailbox1)
        add_callback.reset_mock()
        self.assertEqual(self.model.get_mailbox(b'Foo'), mailbox1)
        self.assertEqual({mbx.name for mbx in self.model.mailboxes()}, {b'INBOX', b'Foo'})

        self.model.add_mailbox(mailbox2)
        add_callback.assert_called_once_with(mailbox2)
        add_callback.reset_mock()
        self.assertEqual(self.model.get_mailbox(b'Foo'), mailbox1)
        self.assertEqual(self.model.get_mailbox(b'Bar'), mailbox2)
        self.assertEqual({mbx.name for mbx in self.model.mailboxes()}, {b'INBOX', b'Foo', b'Bar'})

        self.model.delete_mailbox(b'Foo')
        delete_callback.assert_called_once_with(mailbox1)
        delete_callback.reset_mock()
        self.assertEqual(self.model.get_mailbox(b'Bar'), mailbox2)
        self.assertEqual({mbx.name for mbx in self.model.mailboxes()}, {b'INBOX', b'Bar'})

        self.model.delete_mailbox(b'Bar')
        delete_callback.assert_called_once_with(mailbox2)
        delete_callback.reset_mock()
        self.assertEqual({mbx.name for mbx in self.model.mailboxes()}, {b'INBOX'})

    def test_gmail_msgs(self):
        message = Message(self.model, 1337)
        self.assertEqual(set(self.model.gmail_messages()), set())
        self.model.add_gmail_message(message)
        self.assertEqual(set(self.model.gmail_messages()), {message})
        self.model.delete_gmail_message(1337)
        self.assertEqual(set(self.model.gmail_messages()), set())
