#include <Python.h>

#include "parser.h"

static PyStructSequence_Field address_fields[] = {
	{"name", "bytes or None"},
	{"adl", "bytes or None"},
	{"mailbox", "bytes or None"},
	{"host", "bytes or None"},
	{NULL}
};
static PyStructSequence_Desc address_desc = {
	"imap4.parser.Address",
	"Address in ENVELOPE",
	address_fields,
	4
};
PyTypeObject AddressType;

static PyStructSequence_Field text_body_fields[] = {
	{"type", "always \"text\""},
	{"subtype", "lowercase str"},
	{"params", "dict[lowercase str]->str"},
	{"id", "str or None"},
	{"description", "str or None"},
	{"encoding", "lowercase str"},
	{"size", "int"},
	{"lines", "int"},
	{"md5", "str or None"},
	{"disposition", "(lowercase str, dict[lowercase str]->str) or None"},
	{"lang", "list of str or None"},
	{"location", "str or None"},
	{"extension", "list"},
	{NULL}
};
static PyStructSequence_Desc text_body_desc = {
	"imap4.parser.TextBody",
	"BODYSTRUCTURE with \"text/*\" media type",
	text_body_fields,
	13
};
PyTypeObject TextBodyType;

static PyStructSequence_Field message_body_fields[] = {
	{"type", "always \"message\""},
	{"subtype", "always \"rfc822\""},
	{"params", "dict[lowercase str]->str"},
	{"id", "str or None"},
	{"description", "str or None"},
	{"encoding", "lowercase str"},
	{"size", "int"},
	{"envelope", "Envelope"},
	{"body", "BODYSTRUCTURE type"},
	{"lines", "int"},
	{"md5", "str or None"},
	{"disposition", "(lowercase str, dict[lowercase str]->str) or None"},
	{"lang", "list of str or None"},
	{"location", "str or None"},
	{"extension", "list"},
	{NULL}
};
static PyStructSequence_Desc message_body_desc = {
	"imap4.parser.MessageBody",
	"BODYSTRUCTURE with \"message/rfc822\" media type",
	message_body_fields,
	15
};
PyTypeObject MessageBodyType;

static PyStructSequence_Field basic_body_fields[] = {
	{"type", "lowercase str"},
	{"subtype", "lowercase str"},
	{"params", "dict[lowercase str]->str"},
	{"id", "str or None"},
	{"description", "str or None"},
	{"encoding", "lowercase str"},
	{"size", "int"},
	{"md5", "str or None"},
	{"disposition", "(lowercase str, dict[lowercase str]->str) or None"},
	{"lang", "list of str or None"},
	{"location", "str or None"},
	{"extension", "list"},
	{NULL}
};
static PyStructSequence_Desc basic_body_desc = {
	"imap4.parser.BasicBody",
	"Any other single-part BODYSTRUCTURE",
	basic_body_fields,
	12
};
PyTypeObject BasicBodyType;

static PyStructSequence_Field multipart_body_fields[] = {
	{"type", "always \"multipart\""},
	{"subtype", "lowercase str"},
	{"parts", "list of TextBody, MessageBody, BasicBody, or MultipartBody"},
	{"params", "dict[lowercase str]->str"},
	{"disposition", "(lowercase str, dict[lowercase str]->str) or None"},
	{"lang", "list of str or None"},
	{"location", "str or None"},
	{"extension", "list"},
	{NULL}
};
static PyStructSequence_Desc multipart_body_desc = {
	"imap4.parser.MultipartBody",
	"BODYSTRUCTURE with \"multipart/*\" media type",
	multipart_body_fields,
	8
};
PyTypeObject MultipartBodyType;

static PyStructSequence_Field continue_req_fields[] = {
	{"text", "ResponseText"},
	{NULL},
};
static PyStructSequence_Desc continue_req_desc = {
	"imap4.parser.ContinueReq",
	"Continuation request",
	continue_req_fields,
	1
};
PyTypeObject ContinueReqType;

static PyStructSequence_Field envelope_fields[] = {
	{"date", "datetime.datetime or None"},
	{"subject", "bytes or None"},
	{"from_", "list of Address or None"},
	{"sender", "list of Address or None"},
	{"reply_to", "list of Address or None"},
	{"to", "list of Address or None"},
	{"cc", "list of Address or None"},
	{"bcc", "list of Address or None"},
	{"in_reply_to", "bytes or None"},
	{"message_id", "bytes or None"},
	{NULL}
};
static PyStructSequence_Desc envelope_desc = {
	"imap4.parser.Envelope",
	"ENVELOPE FETCH item",
	envelope_fields,
	10
};
PyTypeObject EnvelopeType;

static PyStructSequence_Field esearch_fields[] = {
	{"tag", "str or None"},
	{"uid", "bool"},
	{"returned",
"mapping from type to type-specific data:\n"
"MIN, MAX, COUNT: int\n"
"ALL: sequence set\n"},
	{NULL}
};
static PyStructSequence_Desc esearch_desc = {
	"imap4.parser.Esearch",
	"ESEARCH response",
	esearch_fields,
	3
};
PyTypeObject EsearchType;

static PyStructSequence_Field fetch_fields[] = {
	{"msg", "message sequence number as int"},
	{"items",
"items - mapping from item to value:\n"
"BODYSTRUCTURE: TextBody, MessageBody, BasicBody, or MultipartBody\n"
"ENVELOPE: Envelope\n"
"FLAGS: set(str)\n"
"INTERNALDATE: datetime.datetime\n"
"RFC822, RFC822.HEADER, RFC822.TEXT: str or None\n"
"RFC822.SIZE: int\n"
"BODY: dict[str]->(bytes, int)\n"
"and origin is an int or None\n"
"UID: int\n"
"MODSEQ: unsigned 63-bit int (CONDSTORE capability)\n"
"X-GM-MSGID: unsigned 64-bit int (X-GM-EXT1 capability)\n"},
	{NULL}
};
static PyStructSequence_Desc fetch_desc = {
	"imap4.parser.Fetch",
	"FETCH response",
	fetch_fields,
	2
};
PyTypeObject FetchType;

static PyStructSequence_Field list_fields[] = {
	{"attributes", "set of name attributes as strings"},
	{"delimiter", "mailbox delimiter as integer (ord(char)) or None"},
	{"mailbox", "mailbox name as bytes"},
	{NULL}
};
static PyStructSequence_Desc list_desc = {
	"imap4.parser.List",
	"LIST or LSUB response",
	list_fields,
	3
};
PyTypeObject ListType;

static PyStructSequence_Field response_text_fields[] = {
	{"text", "human-readable text as str or None"},
	{"code", "bracket-enclosed code type as str or None"},
	{"code_data",
"type-specific code data:\n"
"ALERT, PARSE, READ-ONLY, READ-WRITE, TRYCREATE: None\n"
"HIGHESTMODSEQ, UIDNEXT, UIDVALIDITY, UNSEEN: int\n"
"Anything else: str or None\n"},
	{NULL},
};
static PyStructSequence_Desc response_text_desc = {
	"imap4.parser.ResponseText",
	"Response text",
	response_text_fields,
	3
};
PyTypeObject ResponseTextType;

static PyStructSequence_Field status_fields[] = {
	{"mailbox", "mailbox name as bytes"},
	{"status", "mapping from item to value"},
	{NULL}
};
static PyStructSequence_Desc status_desc = {
	"imap4.parser.Status",
	"STATUS response",
	status_fields,
	2
};
PyTypeObject StatusType;

static PyStructSequence_Field tagged_response_fields[] = {
	{"tag", "response tag as str"},
	{"type", "response type"},
	{"text", "human-readable response text as ResponseText"},
	{NULL}
};
static PyStructSequence_Desc tagged_response_desc = {
	"imap4.parser.TaggedResponse",
	"Tagged response",
	tagged_response_fields,
	3
};
PyTypeObject TaggedResponseType;

static PyStructSequence_Field untagged_response_fields[] = {
	{"type", "response type"},
	{"data",
"type-specific response data:\n"
"OK, NO, BAD, BYE, PREAUTH: ResponseText\n"
"CAPABILITY, ENABLED, FLAGS: set of strings\n"
"ESEARCH: Esearch\n"
"EXISTS, EXPUNGE, RECENT: int\n"
"FETCH: Fetch\n"
"LIST, LSUB: List\n"
"SEARCH: set of integers\n"
"STATUS: Status"},
	{NULL}
};
static PyStructSequence_Desc untagged_response_desc = {
	"imap4.parser.UntaggedResponse",
	"Untagged response",
	untagged_response_fields,
	2
};
PyTypeObject UntaggedResponseType;

int imapparser_add_parser_types(PyObject *m)
{
	if (PyStructSequence_InitType2(&AddressType, &address_desc) < 0)
		return -1;
	Py_INCREF(&AddressType);
	PyModule_AddObject(m, "Address", (PyObject *)&AddressType);

	if (PyStructSequence_InitType2(&TextBodyType, &text_body_desc) < 0)
		return -1;
	Py_INCREF(&TextBodyType);
	PyModule_AddObject(m, "TextBody", (PyObject *)&TextBodyType);

	if (PyStructSequence_InitType2(&MessageBodyType, &message_body_desc) < 0)
		return -1;
	Py_INCREF(&MessageBodyType);
	PyModule_AddObject(m, "MessageBody", (PyObject *)&MessageBodyType);

	if (PyStructSequence_InitType2(&BasicBodyType, &basic_body_desc) < 0)
		return -1;
	Py_INCREF(&BasicBodyType);
	PyModule_AddObject(m, "BasicBody", (PyObject *)&BasicBodyType);

	if (PyStructSequence_InitType2(&MultipartBodyType, &multipart_body_desc) < 0)
		return -1;
	Py_INCREF(&MultipartBodyType);
	PyModule_AddObject(m, "MultipartBody", (PyObject *)&MultipartBodyType);

	if (PyStructSequence_InitType2(&ContinueReqType,
				       &continue_req_desc) < 0)
		return -1;
	Py_INCREF(&ContinueReqType);
	PyModule_AddObject(m, "ContinueReq", (PyObject *)&ContinueReqType);

	if (PyStructSequence_InitType2(&EnvelopeType, &envelope_desc) < 0)
		return -1;
	Py_INCREF(&EnvelopeType);
	PyModule_AddObject(m, "Envelope", (PyObject *)&EnvelopeType);

	if (PyStructSequence_InitType2(&EsearchType, &esearch_desc) < 0)
		return -1;
	Py_INCREF(&EsearchType);
	PyModule_AddObject(m, "Esearch", (PyObject *)&EsearchType);

	if (PyStructSequence_InitType2(&FetchType, &fetch_desc) < 0)
		return -1;
	Py_INCREF(&FetchType);
	PyModule_AddObject(m, "Fetch", (PyObject *)&FetchType);

	if (PyStructSequence_InitType2(&ListType, &list_desc) < 0)
		return -1;
	Py_INCREF(&ListType);
	PyModule_AddObject(m, "List", (PyObject *)&ListType);

	if (PyStructSequence_InitType2(&ResponseTextType,
				       &response_text_desc) < 0)
		return -1;
	Py_INCREF(&ResponseTextType);
	PyModule_AddObject(m, "ResponseText", (PyObject *)&ResponseTextType);

	if (PyStructSequence_InitType2(&StatusType, &status_desc) < 0)
		return -1;
	Py_INCREF(&StatusType);
	PyModule_AddObject(m, "Status", (PyObject *)&StatusType);

	if (PyStructSequence_InitType2(&TaggedResponseType,
				       &tagged_response_desc) < 0)
		return -1;
	Py_INCREF(&TaggedResponseType);
	PyModule_AddObject(m, "TaggedResponse", (PyObject *)&TaggedResponseType);

	if (PyStructSequence_InitType2(&UntaggedResponseType,
				       &untagged_response_desc) < 0)
		return -1;
	Py_INCREF(&UntaggedResponseType);
	PyModule_AddObject(m, "UntaggedResponse", (PyObject *)&UntaggedResponseType);

	return 0;
}
