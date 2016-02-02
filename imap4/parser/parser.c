#include <Python.h>

#include "parser.h"
#include "tokens.h"

PyObject *ParseError;

/* ATOM-CHAR is any CHAR except atom-specials */
static const char atom_specials[128] = {
	['('] = 1, [')'] = 1, ['{'] = 1,
	[' '] = 1, /* SP */
	/* CTL */
	['\x01'] = 1, ['\x02'] = 1, ['\x03'] = 1, ['\x04'] = 1,
	['\x05'] = 1, ['\x06'] = 1, ['\x07'] = 1, ['\x08'] = 1,
	['\x09'] = 1, ['\x0a'] = 1, ['\x0b'] = 1, ['\x0c'] = 1,
	['\x0d'] = 1, ['\x0e'] = 1, ['\x0f'] = 1, ['\x10'] = 1,
	['\x11'] = 1, ['\x12'] = 1, ['\x13'] = 1, ['\x14'] = 1,
	['\x15'] = 1, ['\x16'] = 1, ['\x17'] = 1, ['\x18'] = 1,
	['\x19'] = 1, ['\x1a'] = 1, ['\x1b'] = 1, ['\x1c'] = 1,
	['\x1d'] = 1, ['\x1e'] = 1, ['\x1f'] = 1, ['\x7f'] = 1,
	['%'] = 1, ['*'] = 1, /* list-wildcards */
	['"'] = 1, ['\\'] = 1, /* quoted-specials */
	[']'] = 1, /* resp-specials */
};

/* ASTRING-CHAR = ATOM-CHAR / resp-specials */
static const char astring_reject[128] = {
	['('] = 1, [')'] = 1, ['{'] = 1,
	[' '] = 1, /* SP */
	/* CTL */
	['\x01'] = 1, ['\x02'] = 1, ['\x03'] = 1, ['\x04'] = 1,
	['\x05'] = 1, ['\x06'] = 1, ['\x07'] = 1, ['\x08'] = 1,
	['\x09'] = 1, ['\x0a'] = 1, ['\x0b'] = 1, ['\x0c'] = 1,
	['\x0d'] = 1, ['\x0e'] = 1, ['\x0f'] = 1, ['\x10'] = 1,
	['\x11'] = 1, ['\x12'] = 1, ['\x13'] = 1, ['\x14'] = 1,
	['\x15'] = 1, ['\x16'] = 1, ['\x17'] = 1, ['\x18'] = 1,
	['\x19'] = 1, ['\x1a'] = 1, ['\x1b'] = 1, ['\x1c'] = 1,
	['\x1d'] = 1, ['\x1e'] = 1, ['\x1f'] = 1, ['\x7f'] = 1,
	['%'] = 1, ['*'] = 1, /* list-wildcards */
	['"'] = 1, ['\\'] = 1, /* quoted-specials */
};

static const char date_time_reject[128] = {
	['\r'] = 1, ['\n'] = 1,
	['"'] = 1, ['\\'] = 1, /* quoted-specials */
};

/* A resp-text-code is any TEXT-CHAR except "]" */
static const char resp_text_code_reject[128] = {
	['\r'] = 1, ['\n'] = 1, [']'] = 1,
};

static const char section_spec_reject[128] = {
	['\r'] = 1, ['\n'] = 1, [']'] = 1,
};

/* TEXT-CHAR is any CHAR except CR and LF */
static const char text_reject[128] = {
	['\r'] = 1, ['\n'] = 1,
};

/* A tag character is any ASTRING-CHAR except "+" */
static const char tag_reject[128] = {
	['('] = 1, [')'] = 1, ['{'] = 1,
	[' '] = 1, /* SP */
	/* CTL */
	['\x01'] = 1, ['\x02'] = 1, ['\x03'] = 1, ['\x04'] = 1,
	['\x05'] = 1, ['\x06'] = 1, ['\x07'] = 1, ['\x08'] = 1,
	['\x09'] = 1, ['\x0a'] = 1, ['\x0b'] = 1, ['\x0c'] = 1,
	['\x0d'] = 1, ['\x0e'] = 1, ['\x0f'] = 1, ['\x10'] = 1,
	['\x11'] = 1, ['\x12'] = 1, ['\x13'] = 1, ['\x14'] = 1,
	['\x15'] = 1, ['\x16'] = 1, ['\x17'] = 1, ['\x18'] = 1,
	['\x19'] = 1, ['\x1a'] = 1, ['\x1b'] = 1, ['\x1c'] = 1,
	['\x1d'] = 1, ['\x1e'] = 1, ['\x1f'] = 1, ['\x7f'] = 1,
	['%'] = 1, ['*'] = 1, /* list-wildcards */
	['"'] = 1, ['\\'] = 1, /* quoted-specials */
	['+'] = 1,
};

static PyObject *parse_address(Py_buffer *, Py_ssize_t *);
static PyObject *parse_astring(Py_buffer *, Py_ssize_t *);
static PyObject *parse_atom(Py_buffer *, Py_ssize_t *);
static PyObject *parse_body(Py_buffer *, Py_ssize_t *);
static int parse_bodysection(Py_buffer *, Py_ssize_t *, PyObject *);
static PyObject *parse_body_extension(Py_buffer *, Py_ssize_t *);
static Py_ssize_t parse_body_ext_1part(Py_buffer *, Py_ssize_t *, PyObject *, Py_ssize_t);
static Py_ssize_t parse_body_ext_mpart(Py_buffer *, Py_ssize_t *, PyObject *);
static int parse_body_fields(Py_buffer *, Py_ssize_t *, PyObject *);
static PyObject *parse_body_fld_dsp(Py_buffer *, Py_ssize_t *);
static PyObject *parse_body_fld_lang(Py_buffer *, Py_ssize_t *);
static PyObject *parse_body_fld_param(Py_buffer *, Py_ssize_t *);
static PyObject *parse_body_type_1part(Py_buffer *, Py_ssize_t *);
static PyObject *parse_body_type_mpart(Py_buffer *, Py_ssize_t *);
static PyObject *parse_continue_req(Py_buffer *, Py_ssize_t *);
static PyObject *parse_date_time(Py_buffer *, Py_ssize_t *);
static PyObject *parse_envelope(Py_buffer *, Py_ssize_t *);
static PyObject *parse_env_addrs(Py_buffer *, Py_ssize_t *);
static PyObject *parse_env_date(Py_buffer *, Py_ssize_t *);
static PyObject *parse_esearch_response(Py_buffer *, Py_ssize_t *);
static PyObject *parse_flag_list(Py_buffer *, Py_ssize_t *);
static PyObject *parse_mailbox(Py_buffer *, Py_ssize_t *);
static PyObject *parse_mailbox_list(Py_buffer *, Py_ssize_t *);
static PyObject *parse_mbx_list_flags(Py_buffer *, Py_ssize_t *);
static int parse_message_data(Py_buffer *, Py_ssize_t *, PyObject **, PyObject **);
static PyObject *parse_msg_att(Py_buffer *, Py_ssize_t *);
static PyObject *parse_nstring(Py_buffer *, Py_ssize_t *);
static PyObject *parse_nstring_ascii(Py_buffer *, Py_ssize_t *);
static int _parse_number(Py_buffer *, Py_ssize_t *, unsigned long long *);
static PyObject *parse_number(Py_buffer *, Py_ssize_t *);
static PyObject *parse_response(Py_buffer *, Py_ssize_t *);
static PyObject *parse_response_data(Py_buffer *, Py_ssize_t *);
static PyObject *parse_response_tagged(Py_buffer *, Py_ssize_t *);
static PyObject *parse_resp_text(Py_buffer *, Py_ssize_t *);
static PyObject *parse_search_att(Py_buffer *, Py_ssize_t *);
static PyObject *parse_sequence_set(Py_buffer *, Py_ssize_t *);
static PyObject *parse_status_att(Py_buffer *, Py_ssize_t *);
static PyObject *parse_string(Py_buffer *, Py_ssize_t *);
static PyObject *parse_string_ascii(Py_buffer *, Py_ssize_t *);
static PyObject *parse_string_ascii_lower(Py_buffer *, Py_ssize_t *);

static PyObject *
parser_error(Py_buffer *view, Py_ssize_t cur, const char *format, ...)
{
	va_list ap;

	/* TODO */
	va_start(ap, format);
	PyErr_FormatV(ParseError, format, ap);
	va_end(ap);
	return NULL;
}

PyObject *
parse_response_line(PyObject *self, PyObject *buf)
{
	Py_buffer view;
	Py_ssize_t cur = 0;
	PyObject *res;

	if (PyObject_GetBuffer(buf, &view, PyBUF_SIMPLE) < 0)
		return NULL;

	if (view.len == 0) {
		PyBuffer_Release(&view);
		return parser_error(&view, cur, "nothing to parse");
	}

	res = parse_response(&view, &cur);
	if (res == NULL) {
		PyBuffer_Release(&view);
		return NULL;
	}
	if (cur != view.len) {
		Py_DECREF(res);
		PyBuffer_Release(&view);
		return parser_error(&view, cur, "trailing characters after response");
	}
	PyBuffer_Release(&view);
	return res;
}

PyObject *
parse_imap_string(PyObject *self, PyObject *buf)
{
	Py_buffer view;
	Py_ssize_t cur = 0;
	PyObject *res;

	if (PyObject_GetBuffer(buf, &view, PyBUF_SIMPLE) < 0)
		return NULL;

	if (view.len == 0) {
		PyBuffer_Release(&view);
		return parser_error(&view, cur, "nothing to parse");
	}

	res = parse_string(&view, &cur);
	if (res == NULL) {
		PyBuffer_Release(&view);
		return NULL;
	}
	if (cur != view.len) {
		Py_DECREF(res);
		PyBuffer_Release(&view);
		return parser_error(&view, cur, "trailing characters after string");
	}
	PyBuffer_Release(&view);
	return res;
}

PyObject *
parse_imap_astring(PyObject *self, PyObject *buf)
{
	Py_buffer view;
	Py_ssize_t cur = 0;
	PyObject *res;

	if (PyObject_GetBuffer(buf, &view, PyBUF_SIMPLE) < 0)
		return NULL;

	if (view.len == 0) {
		PyBuffer_Release(&view);
		return parser_error(&view, cur, "nothing to parse");
	}

	res = parse_astring(&view, &cur);
	if (res == NULL) {
		PyBuffer_Release(&view);
		return NULL;
	}
	if (cur != view.len) {
		Py_DECREF(res);
		PyBuffer_Release(&view);
		return parser_error(&view, cur, "trailing characters after astring");
	}
	PyBuffer_Release(&view);
	return res;
}

/* Helpers */

#define PARSE_ERROR(args...) parser_error(view, *cur, args)

#define TRUNCATED_PARSE() parser_error(view, *cur, "truncated parse")

#define PEEKC() ({				\
	if (*cur >= view->len) {		\
		TRUNCATED_PARSE();		\
		goto err;			\
	}					\
	((char *)view->buf)[*cur];		\
})

#define GETC() ({				\
	if (*cur >= view->len) {		\
		TRUNCATED_PARSE();		\
		goto err;			\
	}					\
	((char *)view->buf)[(*cur)++];		\
})

static void
fail_expectc(Py_buffer *view, Py_ssize_t *cur, char c)
{
	PyObject *tmp;

	tmp = PyUnicode_FromStringAndSize(&c, 1);
	if (tmp) {
		PARSE_ERROR("expected %R", tmp);
		Py_DECREF(tmp);
	}
}

#define EXPECTC(c) do {					\
	if (*cur >= view->len) {			\
		TRUNCATED_PARSE();			\
		goto err;				\
	}						\
	if (((char *)view->buf)[*cur] != (c)) {		\
		fail_expectc(view, cur, (c));		\
		goto err;				\
	}						\
	(*cur)++;					\
} while (0)

static PyObject *
fail_expects(Py_buffer *view, Py_ssize_t *cur, const char *s)
{
	PyObject *tmp;

	tmp = PyUnicode_FromString(s);
	if (tmp == NULL)
		return NULL;
	PARSE_ERROR("expected %R", tmp);
	Py_DECREF(tmp);
	return NULL;
}

#define EXPECTS(s) do {							\
	Py_ssize_t __len = strlen((s));					\
	if (*cur + __len > view->len) {					\
		TRUNCATED_PARSE();					\
		goto err;						\
	}								\
	if (memcmp(&((char *)view->buf)[*cur], (s), __len) != 0) {	\
		fail_expects(view, cur, (s));				\
		goto err;						\
	}								\
	(*cur) += __len;						\
} while (0)

static int
bufcspn(Py_buffer *view, Py_ssize_t *cur, const char reject[128],
	char **start_ret, Py_ssize_t *len_ret)
{
	char *start, *end, *p;

	if (*cur >= view->len) {
		TRUNCATED_PARSE();
		return -1;
	}

	start = &((char *)view->buf)[*cur];
	end = &((char *)view->buf)[view->len];
	p = start;
	while ((p != end) && *p >= '\x01' && *p <= '\x7f' && !reject[(unsigned char)*p])
		p++;
	*start_ret = start;
	*len_ret = p - start;
	*cur += *len_ret;
	return 0;
}

static PyObject *
parse_cspn(Py_buffer *view, Py_ssize_t *cur, const char reject[128])
{
	char *str;
	Py_ssize_t len;
	if (bufcspn(view, cur, reject, &str, &len) < 0)
		return NULL;
	if (len == 0) {
		PARSE_ERROR("empty span");
		return NULL;
	}
	return PyUnicode_FromStringAndSize(str, len);
}

static long
parse_token(Py_buffer *view, Py_ssize_t *cur)
{
	long res;
	char *start, *end, *p;
	Py_ssize_t token_len;

	if (*cur >= view->len) {
		TRUNCATED_PARSE();
		return -1;
	}

	start = &((char *)view->buf)[*cur];
	end = &((char *)view->buf)[view->len];
	p = start;
	while ((p != end) &&
	       (('A' <= *p && *p <= 'Z') || ('a' <= *p && *p <= 'z') ||
		('0' <= *p && *p <= '9') || (*p == '.') || (*p == '-')))
		p++;
	token_len = p - start;
	res = imap4_token(start, token_len);
	if (res != 0)
		*cur += token_len;
	return res;
}

static PyObject *
Token_FromLong(long token)
{
	PyObject *module;
	PyObject *token_obj;

	module = PyImport_ImportModule("imap4");
	if (module == NULL)
		return NULL;
	token_obj = PyObject_CallMethod(module, "Token", "(l)", token);
	Py_DECREF(module);
	return token_obj;
}

static int
PyDict_SetItemToken(PyObject *p, long token, PyObject *val)
{
	PyObject *key_obj;

	key_obj = Token_FromLong(token);
	if (key_obj == NULL)
		return -1;
	if (PyDict_SetItem(p, key_obj, val) < 0) {
		Py_DECREF(key_obj);
		return -1;
	}
	Py_DECREF(key_obj);
	return 0;
}

/*
 * address - returns Address
 */
static PyObject *
parse_address(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *address = NULL;
	PyObject *name = NULL;
	PyObject *adl = NULL;
	PyObject *mailbox = NULL;
	PyObject *host = NULL;

	EXPECTC('(');
	/* addr-name */
	name = parse_nstring(view, cur);
	if (name == NULL)
		goto err;
	EXPECTC(' ');
	/* addr-adl */
	adl = parse_nstring(view, cur);
	if (adl == NULL)
		goto err;
	EXPECTC(' ');
	/* addr-mailbox */
	mailbox = parse_nstring(view, cur);
	if (mailbox == NULL)
		goto err;
	EXPECTC(' ');
	/* addr-host */
	host = parse_nstring(view, cur);
	if (host == NULL)
		goto err;
	EXPECTC(')');

	address = PyStructSequence_New(&AddressType);
	if (address == NULL)
		goto err;

	PyStructSequence_SET_ITEM(address, 0, name);
	PyStructSequence_SET_ITEM(address, 1, adl);
	PyStructSequence_SET_ITEM(address, 2, mailbox);
	PyStructSequence_SET_ITEM(address, 3, host);
	return address;

err:
	Py_XDECREF(address);
	Py_XDECREF(name);
	Py_XDECREF(adl);
	Py_XDECREF(mailbox);
	Py_XDECREF(host);
	return NULL;
}

/*
 * astring - returns bytes
 */
static PyObject *
parse_astring(Py_buffer *view, Py_ssize_t *cur)
{
	char c;

	c = PEEKC();
	if (c == '"' || c == '{') {
		return parse_string(view, cur);
	} else {
		char *atom;
		Py_ssize_t atom_len;

		if (bufcspn(view, cur, astring_reject, &atom, &atom_len) < 0)
			goto err;
		if (atom_len == 0) {
			PARSE_ERROR("empty astring");
			return NULL;
		}
		return PyBytes_FromStringAndSize(atom, atom_len);
	}

err:
	return NULL;
}

/*
 * atom - returns str
 */
static inline PyObject *
parse_atom(Py_buffer *view, Py_ssize_t *cur)
{
	return parse_cspn(view, cur, atom_specials);
}

/*
 * body - returns TextBody, MessageBody, BasicBody, or MultipartBody
 */
static PyObject *
parse_body(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *body = NULL;

	EXPECTC('(');
	if (PEEKC() == '(')
		body = parse_body_type_mpart(view, cur);
	else
		body = parse_body_type_1part(view, cur);
	if (body == NULL)
		goto err;
	EXPECTC(')');

	return body;

err:
	Py_XDECREF(body);
	return NULL;
}

/*
 * "BODY" section ["<" number ">"] SP nstring
 */
static int
parse_bodysection(Py_buffer *view, Py_ssize_t *cur, PyObject *dict)
{
	PyObject *section_obj = NULL;
	PyObject *tuple = NULL;
	PyObject *content;
	char *section;
	Py_ssize_t section_len;


	/*
	 * section-spec; we could parse this exactly according to the grammar,
	 * but it's simpler to just assume it's whatever is in the [] brackets.
	 */
	EXPECTC('[');
	if (bufcspn(view, cur, section_spec_reject, &section, &section_len) < 0)
		goto err;
	EXPECTC(']');
	section_obj = PyUnicode_FromStringAndSize(section, section_len);
	if (section_obj == NULL)
		goto err;

	tuple = PyTuple_New(2);
	if (tuple == NULL)
		goto err;

	if (PEEKC() == '<') {
		PyObject *origin;

		GETC();
		origin = parse_number(view, cur);
		if (origin == NULL)
			goto err;
		PyTuple_SET_ITEM(tuple, 1, origin);
		EXPECTC('>');
	} else {
		Py_INCREF(Py_None);
		PyTuple_SET_ITEM(tuple, 1, Py_None);
	}
	EXPECTC(' ');

	content = parse_nstring(view, cur);
	if (content == NULL)
		goto err;
	PyTuple_SET_ITEM(tuple, 0, content);

	if (PyDict_SetItem(dict, section_obj, tuple) < 0)
		goto err;

	Py_DECREF(section_obj);
	Py_DECREF(tuple);
	return 0;

err:
	Py_XDECREF(section_obj);
	Py_XDECREF(tuple);
	return -1;
}

/*
 * body-extension - returns str, int, or list
 */
static PyObject *
parse_body_extension(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *list = NULL;
	char c;

	c = PEEKC();
	if (c == '(') {
		GETC();
		list = PyList_New(0);
		if (list == NULL)
			goto err;
		while (1) {
			PyObject *extension;

			extension = parse_body_extension(view, cur);
			if (extension == NULL)
				goto err;
			if (PyList_Append(list, extension) < 0) {
				Py_DECREF(extension);
				goto err;
			}
			Py_DECREF(extension);
			if (PEEKC() == ')') {
				GETC();
				break;
			}
			EXPECTC(' ');
		}
		return list;
	} else if ('0' <= c && c <= '9') {
		return parse_number(view, cur);
	} else {
		return parse_nstring_ascii(view, cur);
	}

err:
	Py_XDECREF(list);
	return NULL;
}

/*
 * body-ext-1-part - populates body[ext:], returning how many
 */
static Py_ssize_t
parse_body_ext_1part(Py_buffer *view, Py_ssize_t *cur, PyObject *body,
		     Py_ssize_t ext)
{
	PyObject *field;
	PyObject *list = NULL;

	/* body-fld-md5 */
	field = parse_nstring_ascii(view, cur);
	if (field == NULL)
		goto err;
	PyStructSequence_SET_ITEM(body, ext, field);
	ext++;
	if (PEEKC() != ' ')
		return 1;

	GETC();
	field = parse_body_fld_dsp(view, cur);
	if (field == NULL)
		goto err;
	PyStructSequence_SET_ITEM(body, ext, field);
	ext++;
	if (PEEKC() != ' ')
		return 2;

	GETC();
	field = parse_body_fld_lang(view, cur);
	if (field == NULL)
		goto err;
	PyStructSequence_SET_ITEM(body, ext, field);
	ext++;
	if (PEEKC() != ' ')
		return 3;

	/* body-fld-loc */
	GETC();
	field = parse_nstring_ascii(view, cur);
	if (field == NULL)
		goto err;
	PyStructSequence_SET_ITEM(body, ext, field);
	ext++;
	if (PEEKC() != ' ')
		return 4;

	list = PyList_New(0);
	if (list == NULL)
		goto err;
	while (PEEKC() == ' ') {
		GETC();
		field = parse_body_extension(view, cur);
		if (field == NULL)
			goto err;
		if (PyList_Append(list, field) < 0) {
			Py_DECREF(field);
			goto err;
		}
		Py_DECREF(field);
	}
	PyStructSequence_SET_ITEM(body, ext, list);
	return 5;

err:
	Py_XDECREF(list);
	return -1;
}

/*
 * body-ext-mpart - populates body[3:], returning how many
 */
static Py_ssize_t
parse_body_ext_mpart(Py_buffer *view, Py_ssize_t *cur, PyObject *body)
{
	PyObject *field;
	PyObject *list = NULL;

	field = parse_body_fld_param(view, cur);
	if (field == NULL)
		goto err;
	PyStructSequence_SET_ITEM(body, 3, field);
	if (PEEKC() != ' ')
		return 1;

	GETC();
	field = parse_body_fld_dsp(view, cur);
	if (field == NULL)
		goto err;
	PyStructSequence_SET_ITEM(body, 4, field);
	if (PEEKC() != ' ')
		return 2;

	GETC();
	field = parse_body_fld_lang(view, cur);
	if (field == NULL)
		goto err;
	PyStructSequence_SET_ITEM(body, 5, field);
	if (PEEKC() != ' ')
		return 3;

	/* body-fld-loc */
	GETC();
	field = parse_nstring_ascii(view, cur);
	if (field == NULL)
		goto err;
	PyStructSequence_SET_ITEM(body, 6, field);
	if (PEEKC() != ' ')
		return 4;

	list = PyList_New(0);
	if (list == NULL)
		goto err;
	while (PEEKC() == ' ') {
		GETC();
		field = parse_body_extension(view, cur);
		if (field == NULL)
			goto err;
		if (PyList_Append(list, field) < 0) {
			Py_DECREF(field);
			goto err;
		}
		Py_DECREF(field);
	}
	PyStructSequence_SET_ITEM(body, 7, list);
	return 5;

err:
	Py_XDECREF(list);
	return -1;
}

/*
 * body-fields - populates body[2:7]
 */
static int
parse_body_fields(Py_buffer *view, Py_ssize_t *cur, PyObject *body)
{
	PyObject *field;

	field = parse_body_fld_param(view, cur);
	if (field == NULL)
		goto err;
	PyStructSequence_SET_ITEM(body, 2, field);
	EXPECTC(' ');

	/* body-fld-id */
	field = parse_nstring_ascii(view, cur);
	if (field == NULL)
		goto err;
	PyStructSequence_SET_ITEM(body, 3, field);
	EXPECTC(' ');

	/* body-fld-desc */
	field = parse_nstring_ascii(view, cur);
	if (field == NULL)
		goto err;
	PyStructSequence_SET_ITEM(body, 4, field);
	EXPECTC(' ');

	/* body-fld-enc */
	field = parse_string_ascii_lower(view, cur);
	if (field == NULL)
		goto err;
	PyStructSequence_SET_ITEM(body, 5, field);
	EXPECTC(' ');

	/* body-fld-octets */
	field = parse_number(view, cur);
	if (field == NULL)
		goto err;
	PyStructSequence_SET_ITEM(body, 6, field);

	return 0;

err:
	return -1;
}

/*
 * body-fld-dsp - returns (lowercase str, dict[lowercase str]->str) or None
 */
static PyObject *
parse_body_fld_dsp(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *tuple = NULL;
	PyObject *type = NULL;
	PyObject *params = NULL;

	if (PEEKC() != '(') {
		EXPECTS("NIL");
		Py_RETURN_NONE;
	}

	GETC();
	type = parse_string_ascii_lower(view, cur);
	if (type == NULL)
		goto err;
	EXPECTC(' ');
	params = parse_body_fld_param(view, cur);
	if (params == NULL)
		goto err;
	EXPECTC(')');
	tuple = PyTuple_New(2);
	if (tuple == NULL)
		goto err;
	PyTuple_SET_ITEM(tuple, 0, type);
	PyTuple_SET_ITEM(tuple, 1, params);
	return tuple;

err:
	Py_XDECREF(tuple);
	Py_XDECREF(type);
	Py_XDECREF(params);
	return NULL;
}

/*
 * body-fld-lang - returns list of str or None
 */
static PyObject *
parse_body_fld_lang(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *list = NULL;

	if (PEEKC() != '(') {
		PyObject *lang;

		lang = parse_nstring_ascii(view, cur);
		if (lang == NULL)
			goto err;
		if (lang == Py_None)
			return lang;

		list = PyList_New(1);
		if (list == NULL) {
			Py_DECREF(lang);
			goto err;
		}
		PyList_SET_ITEM(list, 0, lang);
		return list;
	}

	list = PyList_New(0);
	if (list == NULL)
		goto err;

	GETC();
	while (1) {
		PyObject *lang;

		lang = parse_string_ascii(view, cur);
		if (lang == NULL)
			goto err;
		if (PyList_Append(list, lang) < 0) {
			Py_DECREF(lang);
			goto err;
		}
		Py_DECREF(lang);
		if (PEEKC() == ')') {
			GETC();
			break;
		}
		EXPECTC(' ');
	}

	return list;

err:
	Py_XDECREF(list);
	return NULL;
}

/*
 * body-fld-param - returns dict[lowercase str]->str
 */
static PyObject *
parse_body_fld_param(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *params = NULL;
	PyObject *key = NULL;
	PyObject *value = NULL;

	params = PyDict_New();
	if (params == NULL)
		goto err;

	if (PEEKC() != '(') {
		EXPECTS("NIL");
		return params;
	}

	GETC();
	while (1) {
		key = parse_string_ascii_lower(view, cur);
		if (key == NULL)
			goto err;
		EXPECTC(' ');
		value = parse_string_ascii(view, cur);
		if (value == NULL)
			goto err;
		if (PyDict_SetItem(params, key, value) < 0)
			goto err;
		Py_DECREF(key);
		Py_DECREF(value);
		key = NULL;
		value = NULL;
		if (PEEKC() == ')') {
			GETC();
			break;
		}
		EXPECTC(' ');
	}

	return params;

err:
	Py_XDECREF(params);
	Py_XDECREF(key);
	Py_XDECREF(value);
	return NULL;
}

/*
 * body-type-1part - returns TextBody, MessageBody, or BasicBody
 */
static PyObject *
parse_body_type_1part(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *body = NULL;
	PyObject *media_type = NULL;
	PyObject *media_subtype = NULL;
	PyObject *field;
	Py_ssize_t ext;
	Py_ssize_t num_ext = 0;

	media_type = parse_string_ascii_lower(view, cur);
	if (media_type == NULL)
		goto err;
	EXPECTC(' ');
	media_subtype = parse_string_ascii_lower(view, cur);
	if (media_subtype == NULL)
		goto err;
	EXPECTC(' ');

	if (PyUnicode_CompareWithASCIIString(media_type, "text") == 0) {
		/* body-type-text */
		body = PyStructSequence_New(&TextBodyType);
		if (body == NULL)
			goto err;
		if (parse_body_fields(view, cur, body) < 0)
			goto err;
		EXPECTC(' ');

		/* body-fld-lines */
		field = parse_number(view, cur);
		if (field == NULL)
			goto err;
		PyStructSequence_SET_ITEM(body, 7, field);

		ext = 8;
	} else if (PyUnicode_CompareWithASCIIString(media_type, "message") == 0 &&
		   PyUnicode_CompareWithASCIIString(media_subtype, "rfc822") == 0) {
		/* body-type-msg */
		body = PyStructSequence_New(&MessageBodyType);
		if (body == NULL)
			goto err;
		if (parse_body_fields(view, cur, body) < 0)
			goto err;
		EXPECTC(' ');

		field = parse_envelope(view, cur);
		if (field == NULL)
			goto err;
		PyStructSequence_SET_ITEM(body, 7, field);
		EXPECTC(' ');

		field = parse_body(view, cur);
		if (field == NULL)
			goto err;
		PyStructSequence_SET_ITEM(body, 8, field);
		EXPECTC(' ');

		/* body-fld-lines */
		field = parse_number(view, cur);
		if (field == NULL)
			goto err;
		PyStructSequence_SET_ITEM(body, 9, field);

		ext = 10;
	} else {
		/* body-type-basic */
		body = PyStructSequence_New(&BasicBodyType);
		if (body == NULL)
			goto err;
		if (parse_body_fields(view, cur, body) < 0)
			goto err;
		ext = 7;
	}

	if (PEEKC() == ' ') {
		GETC();
		num_ext = parse_body_ext_1part(view, cur, body, ext);
		if (num_ext < 0)
			goto err;
		ext += num_ext;
	}
	while (num_ext < 5) {
		if (num_ext < 4) {
			Py_INCREF(Py_None);
			PyStructSequence_SET_ITEM(body, ext, Py_None);
		} else {
			field = PyList_New(0);
			if (field == NULL)
				goto err;
			PyStructSequence_SET_ITEM(body, ext, field);
		}
		num_ext++;
		ext++;
	}

	PyStructSequence_SET_ITEM(body, 0, media_type);
	PyStructSequence_SET_ITEM(body, 1, media_subtype);
	return body;

err:
	Py_XDECREF(body);
	Py_XDECREF(media_type);
	Py_XDECREF(media_subtype);
	return NULL;
}

/*
 * body-type-mpart - returns MultipartBody
 */
static PyObject *
parse_body_type_mpart(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *body = NULL;
	PyObject *parts = NULL;
	PyObject *media_type = NULL;
	PyObject *media_subtype = NULL;
	PyObject *field;
	Py_ssize_t num_ext = 0;

	parts = PyList_New(0);
	if (parts == NULL)
		goto err;

	while (PEEKC() == '(') {
		PyObject *body;

		body = parse_body(view, cur);
		if (body == NULL)
			goto err;
		if (PyList_Append(parts, body) < 0) {
			Py_DECREF(body);
			goto err;
		}
		Py_DECREF(body);
	}
	EXPECTC(' ');

	media_type = PyUnicode_FromString("multipart");
	if (media_type == NULL)
		goto err;
	media_subtype = parse_string_ascii_lower(view, cur);
	if (media_subtype == NULL)
		goto err;

	body = PyStructSequence_New(&MultipartBodyType);
	if (body == NULL)
		goto err;

	if (PEEKC() == ' ') {
		GETC();
		num_ext = parse_body_ext_mpart(view, cur, body);
		if (num_ext < 0)
			goto err;
	}
	while (num_ext < 5) {
		if (num_ext == 0) {
			field = PyDict_New();
			if (field == NULL)
				goto err;
			PyStructSequence_SET_ITEM(body, 3, field);
		} else if (num_ext < 4) {
			Py_INCREF(Py_None);
			PyStructSequence_SET_ITEM(body, 3 + num_ext, Py_None);
		} else {
			field = PyList_New(0);
			if (field == NULL)
				goto err;
			PyStructSequence_SET_ITEM(body, 7, field);
		}
		num_ext++;
	}

	PyStructSequence_SET_ITEM(body, 0, media_type);
	PyStructSequence_SET_ITEM(body, 1, media_subtype);
	PyStructSequence_SET_ITEM(body, 2, parts);
	return body;

err:
	Py_XDECREF(body);
	Py_XDECREF(parts);
	Py_XDECREF(media_type);
	Py_XDECREF(media_subtype);
	return NULL;
}

/*
 * continue-req - returns ContinueReq
 */
static PyObject *
parse_continue_req(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *resp = NULL;
	PyObject *text = NULL;

	EXPECTS("+ ");
	text = parse_resp_text(view, cur);
	if (text == NULL)
		goto err;
	EXPECTS("\r\n");

	resp = PyStructSequence_New(&ContinueReqType);
	if (resp == NULL)
		goto err;
	PyStructSequence_SET_ITEM(resp, 0, text);
	return resp;

err:
	Py_XDECREF(resp);
	Py_XDECREF(text);
	return NULL;
}

/*
 * date-time - returns datetime
 */
static PyObject *
parse_date_time(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *str = NULL;
	PyObject *res;
	PyObject *datetime_module;
	PyObject *datetime_class;

	EXPECTC('"');
	str = parse_cspn(view, cur, date_time_reject);
	if (str == NULL)
		goto err;
	EXPECTC('"');

	/* Call datetime.datetime.strptime() */
	datetime_module = PyImport_ImportModule("datetime");
	if (datetime_module == NULL)
		goto err;

	datetime_class = PyObject_GetAttrString(datetime_module, "datetime");
	if (datetime_class == NULL) {
		Py_DECREF(datetime_module);
		goto err;
	}
	Py_DECREF(datetime_module);

	res = PyObject_CallMethod(datetime_class, "strptime", "Os", str,
				  "%d-%b-%Y %H:%M:%S %z");
	if (res == NULL) {
		Py_DECREF(datetime_class);
		if (PyErr_ExceptionMatches(PyExc_ValueError)) {
			PyErr_Clear();
			PARSE_ERROR("invalid date");
		}
		goto err;
	}
	Py_DECREF(datetime_class);

	Py_DECREF(str);
	return res;

err:
	Py_XDECREF(str);
	return NULL;
}

/*
 * envelope - returns Envelope
 */
static PyObject *
parse_envelope(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *envelope = NULL;
	PyObject *date = NULL;
	PyObject *subject = NULL;
	PyObject *from = NULL;
	PyObject *sender = NULL;
	PyObject *reply_to = NULL;
	PyObject *to = NULL;
	PyObject *cc = NULL;
	PyObject *bcc = NULL;
	PyObject *in_reply_to = NULL;
	PyObject *message_id = NULL;

	EXPECTC('(');
	date = parse_env_date(view, cur);
	if (date == NULL)
		goto err;
	EXPECTC(' ');
	/* env-subject */
	subject = parse_nstring(view, cur);
	if (subject == NULL)
		goto err;
	EXPECTC(' ');
	/* env-from */
	from = parse_env_addrs(view, cur);
	if (from == NULL)
		goto err;
	EXPECTC(' ');
	/* env-sender */
	sender = parse_env_addrs(view, cur);
	if (sender == NULL)
		goto err;
	EXPECTC(' ');
	/* env-reply-to */
	reply_to = parse_env_addrs(view, cur);
	if (reply_to == NULL)
		goto err;
	EXPECTC(' ');
	/* env-to */
	to = parse_env_addrs(view, cur);
	if (to == NULL)
		goto err;
	EXPECTC(' ');
	/* env-cc */
	cc = parse_env_addrs(view, cur);
	if (cc == NULL)
		goto err;
	EXPECTC(' ');
	/* env-bcc */
	bcc = parse_env_addrs(view, cur);
	if (bcc == NULL)
		goto err;
	EXPECTC(' ');
	/* env-in-reply-to */
	in_reply_to = parse_nstring(view, cur);
	if (in_reply_to == NULL)
		goto err;
	EXPECTC(' ');
	/* env-message-id */
	message_id = parse_nstring(view, cur);
	if (message_id == NULL)
		goto err;
	EXPECTC(')');

	envelope = PyStructSequence_New(&EnvelopeType);
	if (envelope == NULL)
		goto err;
	PyStructSequence_SET_ITEM(envelope, 0, date);
	PyStructSequence_SET_ITEM(envelope, 1, subject);
	PyStructSequence_SET_ITEM(envelope, 2, from);
	PyStructSequence_SET_ITEM(envelope, 3, sender);
	PyStructSequence_SET_ITEM(envelope, 4, reply_to);
	PyStructSequence_SET_ITEM(envelope, 5, to);
	PyStructSequence_SET_ITEM(envelope, 6, cc);
	PyStructSequence_SET_ITEM(envelope, 7, bcc);
	PyStructSequence_SET_ITEM(envelope, 8, in_reply_to);
	PyStructSequence_SET_ITEM(envelope, 9, message_id);
	return envelope;

err:
	Py_XDECREF(envelope);
	Py_XDECREF(date);
	Py_XDECREF(subject);
	Py_XDECREF(from);
	Py_XDECREF(sender);
	Py_XDECREF(reply_to);
	Py_XDECREF(to);
	Py_XDECREF(cc);
	Py_XDECREF(bcc);
	Py_XDECREF(in_reply_to);
	Py_XDECREF(message_id);
	return NULL;
}

/*
 * env-bcc, env-cc, env-from, env-reply-to, env-sender, env-to - returns list of
 * Address or None
 */
static PyObject *
parse_env_addrs(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *list = NULL;

	if (PEEKC() == 'N') {
		EXPECTS("NIL");
		Py_RETURN_NONE;
	}

	list = PyList_New(0);
	if (list == NULL)
		goto err;

	EXPECTC('(');
	while (1) {
		PyObject *item;

		item = parse_address(view, cur);
		if (item == NULL)
			goto err;
		if (PyList_Append(list, item) < 0) {
			Py_DECREF(item);
			goto err;
		}
		Py_DECREF(item);
		if (PEEKC() != '(')
			break;
	}
	EXPECTC(')');

	return list;

err:
	Py_XDECREF(list);
	return NULL;
}

/*
 * env-date - returns datetime or None
 */
static PyObject *
parse_env_date(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *str = NULL;
	PyObject *res;
	PyObject *email_utils_module;

	str = parse_nstring_ascii(view, cur);
	if (str == NULL)
		goto err;

	if (str == Py_None)
		return str;

	/* call email.utils.parsedate_to_datetime() */
	email_utils_module = PyImport_ImportModule("email.utils");
	if (email_utils_module == NULL)
		goto err;

	res = PyObject_CallMethod(email_utils_module, "parsedate_to_datetime",
				  "(O)", str);
	if (res == NULL) {
		Py_DECREF(email_utils_module);
		if (PyErr_ExceptionMatches(PyExc_TypeError)) {
			/*
			 * As of Python 3.5.1, parsedate_to_datetime() for a
			 * bogus date will try to unpack None and end up with a
			 * TypeError as a result.
			 */
			PyErr_Clear();
			Py_DECREF(str);
			Py_RETURN_NONE;
		}
		goto err;
	}
	Py_DECREF(email_utils_module);

	Py_DECREF(str);
	return res;

err:
	Py_XDECREF(str);
	return NULL;
}

/*
 * esearch-response - returns Esearch
 */
static PyObject *
parse_esearch_response(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *data = NULL;
	PyObject *tag = NULL;
	PyObject *returned = NULL;
	long uid;

	returned = PyDict_New();
	if (returned == NULL)
		goto err;

	/* "ESEARCH" has already been parsed */

	if (PEEKC() != ' ') {
		data = PyStructSequence_New(&EsearchType);
		if (data == NULL)
			goto err;
		Py_INCREF(Py_None);
		PyStructSequence_SET_ITEM(data, 0, Py_None);
		Py_INCREF(Py_False);
		PyStructSequence_SET_ITEM(data, 1, Py_False);
		PyStructSequence_SET_ITEM(data, 2, returned);
		return data;
	}
	GETC();

	if (PEEKC() == '(') {
		/* search-correlator */
		EXPECTS("(TAG ");
		tag = parse_string_ascii(view, cur);
		EXPECTC(')');
	} else {
		Py_INCREF(Py_None);
		tag = Py_None;
	}

	uid = 0;
	while (PEEKC() == ' ') {
		long token;
		PyObject *value;

		GETC();
		token = parse_token(view, cur);
		if (token < 0)
			goto err;
		switch (token) {
		case IMAP4_UID:
			uid = 1;
			break;
		case IMAP4_COUNT:
		case IMAP4_MAX:
		case IMAP4_MIN:
			EXPECTC(' ');
			value = parse_number(view, cur);
			if (value == NULL)
				goto err;
			if (PyDict_SetItemToken(returned, token, value) < 0) {
				Py_DECREF(value);
				goto err;
			}
			Py_DECREF(value);
			break;
		case IMAP4_ALL:
			EXPECTC(' ');
			value = parse_sequence_set(view, cur);
			if (value == NULL)
				goto err;
			if (PyDict_SetItemToken(returned, token, value) < 0) {
				Py_DECREF(value);
				goto err;
			}
			Py_DECREF(value);
			break;
		default:
			PARSE_ERROR("unknown ESEARCH return");
			goto err;
		}
	}

	data = PyStructSequence_New(&EsearchType);
	if (data == NULL)
		goto err;
	PyStructSequence_SET_ITEM(data, 0, tag);
	PyStructSequence_SET_ITEM(data, 1, PyBool_FromLong(uid));
	PyStructSequence_SET_ITEM(data, 2, returned);
	return data;

err:
	Py_XDECREF(data);
	Py_XDECREF(tag);
	Py_XDECREF(returned);
	return NULL;
}

/*
 * flag-list - returns set of strings
 */
static PyObject *parse_flag_list(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *flags = NULL;
	char *atom;
	Py_ssize_t atom_len;

	flags = PySet_New(NULL);
	if (flags == NULL)
		goto err;
	EXPECTC('(');
	if (PEEKC() == ')') {
		GETC();
		return flags;
	}
	while (1) {
		PyObject *flag;
		if (PEEKC() == '\\') {
			/* flag-extension */
			GETC();
			if (bufcspn(view, cur, atom_specials, &atom, &atom_len) < 0)
				goto err;
			if (atom_len == 0) {
				PARSE_ERROR("empty atom");
				goto err;
			}
			flag = PyUnicode_FromStringAndSize(atom - 1, atom_len + 1);
		} else {
			flag = parse_atom(view, cur);
		}
		if (flag == NULL)
			goto err;
		if (PySet_Add(flags, flag) < 0) {
			Py_DECREF(flag);
			goto err;
		}
		Py_DECREF(flag);
		if (PEEKC() != ' ')
			break;
		GETC();
	}
	EXPECTC(')');
	return flags;

err:
	Py_XDECREF(flags);
	return NULL;
}

/*
 * mailbox - returns bytes
 */
static PyObject *
parse_mailbox(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *mailbox;
	char *buffer;
	Py_ssize_t length;

	mailbox = parse_astring(view, cur);
	if (mailbox == NULL)
		return NULL;
	if (PyBytes_AsStringAndSize(mailbox, &buffer, &length) < 0) {
		Py_DECREF(mailbox);
		return NULL;
	}
	if (length == 5 && strncasecmp(buffer, "INBOX", 5) == 0)
		memcpy(buffer, "INBOX", 5);
	return mailbox;
}

/*
 * mailbox-list
 */
static PyObject *
parse_mailbox_list(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *data = NULL;
	PyObject *mailbox = NULL;
	PyObject *delimiter = NULL;
	PyObject *flags = NULL;

	flags = parse_mbx_list_flags(view, cur);
	if (flags == NULL)
		goto err;
	EXPECTC(' ');
	if (PEEKC() == '"') {
		char c;

		GETC();
		c = GETC();
		EXPECTS("\" ");
		delimiter = PyLong_FromLong(c);
		if (delimiter == NULL)
			goto err;
	} else {
		EXPECTS("NIL ");
		Py_INCREF(Py_None);
		delimiter = Py_None;
	}
	mailbox = parse_mailbox(view, cur);
	if (mailbox == NULL)
		goto err;

	data = PyStructSequence_New(&ListType);
	if (data == NULL)
		goto err;
	PyStructSequence_SET_ITEM(data, 0, flags);
	PyStructSequence_SET_ITEM(data, 1, delimiter);
	PyStructSequence_SET_ITEM(data, 2, mailbox);
	return data;

err:
	Py_XDECREF(data);
	Py_XDECREF(mailbox);
	Py_XDECREF(delimiter);
	Py_XDECREF(flags);
	return NULL;
}

static PyObject *
parse_mbx_list_flags(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *flags = NULL;
	char *atom;
	Py_ssize_t atom_len;

	flags = PySet_New(NULL);
	if (flags == NULL)
		goto err;
	EXPECTC('(');
	if (PEEKC() == ')') {
		GETC();
		return flags;
	}
	while (1) {
		PyObject *flag;

		/* flag-extension */
		EXPECTC('\\');
		if (bufcspn(view, cur, atom_specials, &atom, &atom_len) < 0)
			goto err;
		if (atom_len == 0) {
			PARSE_ERROR("empty atom");
			goto err;
		}
		flag = PyUnicode_FromStringAndSize(atom - 1, atom_len + 1);
		if (flag == NULL)
			goto err;
		if (PySet_Add(flags, flag) < 0) {
			Py_DECREF(flag);
			goto err;
		}
		Py_DECREF(flag);
		if (PEEKC() != ' ')
			break;
		GETC();
	}
	EXPECTC(')');
	return flags;

err:
	Py_XDECREF(flags);
	return NULL;
}

/*
 * message-data
 *
 * In the ABNF, message-data is only for EXPUNGE and
 * FETCH. However, some mailbox-data also starts with a
 * number and it's easier to handle here.
 */
static int
parse_message_data(Py_buffer *view, Py_ssize_t *cur,
		   PyObject **type_ret, PyObject **data_ret)
{
	PyObject *type = NULL;
	PyObject *data = NULL;
	long token;
	unsigned long long number;

	if (_parse_number(view, cur, &number) < 0)
		goto err;
	EXPECTC(' ');

	token = parse_token(view, cur);
	if (token < 0)
		goto err;
	type = Token_FromLong(token);
	if (type == NULL)
		goto err;
	switch (token) {
	case IMAP4_FETCH:
	{
		PyObject *msg_att;
		PyObject *num_obj;

		EXPECTC(' ');
		num_obj = PyLong_FromUnsignedLongLong(number);
		if (num_obj == NULL)
			goto err;
		msg_att = parse_msg_att(view, cur);
		if (msg_att == NULL) {
			Py_DECREF(num_obj);
			goto err;
		}
		data = PyStructSequence_New(&FetchType);
		if (data == NULL) {
			Py_DECREF(msg_att);
			Py_DECREF(num_obj);
			goto err;
		}
		PyStructSequence_SET_ITEM(data, 0, num_obj);
		PyStructSequence_SET_ITEM(data, 1, msg_att);
		break;
	}
	case IMAP4_EXISTS:
	case IMAP4_EXPUNGE:
	case IMAP4_RECENT:
		data = PyLong_FromUnsignedLongLong(number);
		if (data == NULL)
			goto err;
		break;
	default:
		PARSE_ERROR("unknown message data");
		goto err;
	}

	*type_ret = type;
	*data_ret = data;
	return 0;

err:
	Py_XDECREF(type);
	Py_XDECREF(data);
	return -1;
}

/*
 * msg-att
 */
static PyObject *
parse_msg_att(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *data = NULL;
	PyObject *bodysections = NULL;

	data = PyDict_New();
	if (data == NULL)
		goto err;

	EXPECTC('(');
	while (1) {
		long token;
		PyObject *att_data;
		unsigned long long number;

		token = parse_token(view, cur);
		if (token < 0)
			goto err;
		switch (token) {
		/* msg-att-dynamic */
		case IMAP4_FLAGS:
			EXPECTC(' ');
			att_data = parse_flag_list(view, cur);
			break;
		/* msg-att-static */
		case IMAP4_BODY:
			if (PEEKC() == '[') {
				if (bodysections == NULL) {
					bodysections = PyDict_New();
					if (bodysections == NULL)
						goto err;
					if (PyDict_SetItemToken(data, IMAP4_BODYSECTIONS, bodysections) < 0)
						goto err;
				}
				if (parse_bodysection(view, cur, bodysections) < 0)
					goto err;
				goto skip_setitem;
			}
			/* fallthrough */
		case IMAP4_BODYSTRUCTURE:
			EXPECTC(' ');
			att_data = parse_body(view, cur);
			break;
		case IMAP4_ENVELOPE:
			EXPECTC(' ');
			att_data = parse_envelope(view, cur);
			break;
		case IMAP4_INTERNALDATE:
			EXPECTC(' ');
			att_data = parse_date_time(view, cur);
			break;
		case IMAP4_MODSEQ:
			EXPECTS(" (");
			if (_parse_number(view, cur, &number) < 0)
				goto err;
			EXPECTC(')');
			att_data = PyLong_FromUnsignedLongLong(number);
			break;
		case IMAP4_RFC822:
		case IMAP4_RFC822_HEADER:
		case IMAP4_RFC822_TEXT:
			EXPECTC(' ');
			att_data = parse_nstring(view, cur);
			break;
		case IMAP4_RFC822_SIZE:
		case IMAP4_UID:
		case IMAP4_X_GM_MSGID:
			EXPECTC(' ');
			att_data = parse_number(view, cur);
			break;
		default:
			PARSE_ERROR("unknown FETCH item");
			goto err;
		}
		if (att_data == NULL)
			goto err;
		if (PyDict_SetItemToken(data, token, att_data) < 0) {
			Py_DECREF(att_data);
			goto err;
		}
		Py_DECREF(att_data);

skip_setitem:
		if (PEEKC() != ' ')
			break;
		GETC();
	}
	EXPECTC(')');

	Py_XDECREF(bodysections);
	return data;

err:
	Py_XDECREF(data);
	Py_XDECREF(bodysections);
	return NULL;
}

/*
 * nstring - returns bytes
 */
static inline PyObject *
parse_nstring(Py_buffer *view, Py_ssize_t *cur)
{
	if (PEEKC() == 'N') {
		EXPECTS("NIL");
		Py_RETURN_NONE;
	} else {
		return parse_string(view, cur);
	}

err:
	return NULL;
}

/*
 * nstring - returns bytes
 */
static inline PyObject *
parse_nstring_ascii(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *bytes;
	PyObject *str;

	bytes = parse_nstring(view, cur);
	if (bytes == NULL)
		return NULL;
	if (bytes == Py_None)
		return bytes;
	str = PyUnicode_FromEncodedObject(bytes, "ascii", "strict");
	Py_DECREF(bytes);
	return str;
}

/*
 * number
 */
static int
_parse_number(Py_buffer *view, Py_ssize_t *cur, unsigned long long *ret)
{
	unsigned long long res = 0;
	char *start, *end, *p;

	if (*cur >= view->len) {
		TRUNCATED_PARSE();
		return -1;
	}

	start = &((char *)view->buf)[*cur];
	end = &((char *)view->buf)[view->len];
	p = start;
	while ((p != end) && ('0' <= *p && *p <= '9')) {
		unsigned long long digit = *p - '0';
		if ((res > ULLONG_MAX / 10ULL) ||
		    ((res == ULLONG_MAX / 10ULL) && (digit > ULLONG_MAX % 10ULL))) {
			PARSE_ERROR("number overflowed");
			return -1;
		}
		res *= 10;
		res += digit;
		p++;
	}
	if (p == start) {
		PARSE_ERROR("expected number");
		return -1;
	}
	*ret = res;
	*cur += p - start;
	return 0;
}

/*
 * number - returns int
 */
static inline PyObject *
parse_number(Py_buffer *view, Py_ssize_t *cur)
{
	unsigned long long number;

	if (_parse_number(view, cur, &number) < 0)
		return NULL;
	return PyLong_FromUnsignedLongLong(number);
}

/*
 * response - returns ContinueReq, TaggedResponse, or UntaggedResponse
 */
static PyObject *
parse_response(Py_buffer *view, Py_ssize_t *cur)
{
	char c;

	c = PEEKC();
	if (c == '*') {
		return parse_response_data(view, cur);
	} else if (c == '+') {
		return parse_continue_req(view, cur);
	} else {
		/*
		 * In ABNF, we have response-done = response-tagged /
		 * response-fatal, but response-fatal will get caught by
		 * response-data above, so we just need to parse response-tagged.
		 */
		return parse_response_tagged(view, cur);
	}

err:
	return NULL;
}

/*
 * response-data - returns UntaggedResponse
 */
static PyObject *
parse_response_data(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *resp = NULL;
	PyObject *type = NULL;
	PyObject *data = NULL;
	long token;
	char c;

	EXPECTS("* ");

	c = PEEKC();
	if ('0' <= c && c <= '9') {
		if (parse_message_data(view, cur, &type, &data) < 0)
			goto err;
	} else {
		token = parse_token(view, cur);
		if (token < 0)
			goto err;
		type = Token_FromLong(token);
		if (type == NULL)
			goto err;
		switch (token) {
		case IMAP4_OK:
		case IMAP4_NO:
		case IMAP4_BAD:
		case IMAP4_PREAUTH:
		case IMAP4_BYE:
			/* resp-cond-state, resp-cond-auth, and resp-cond-bye */
			EXPECTC(' ');
			data = parse_resp_text(view, cur);
			if (data == NULL)
				goto err;
			break;
		case IMAP4_CAPABILITY:
		case IMAP4_ENABLED:
			/* capability-data, enable-data */
			data = PySet_New(NULL);
			if (data == NULL)
				goto err;
			while (PEEKC() == ' ') {
				PyObject *cap;
				GETC();
				cap = parse_atom(view, cur);
				if (cap == NULL)
					goto err;
				if (PySet_Add(data, cap) < 0) {
					Py_DECREF(cap);
					goto err;
				}
				Py_DECREF(cap);
			}
			break;
		/* mailbox-data */
		case IMAP4_ESEARCH:
			data = parse_esearch_response(view, cur);
			if (data == NULL)
				goto err;
			break;
		case IMAP4_FLAGS:
			EXPECTC(' ');
			data = parse_flag_list(view, cur);
			if (data == NULL)
				goto err;
			break;
		case IMAP4_LIST:
		case IMAP4_LSUB:
			EXPECTC(' ');
			data = parse_mailbox_list(view, cur);
			if (data == NULL)
				goto err;
			break;
		case IMAP4_SEARCH:
			data = parse_search_att(view, cur);
			if (data == NULL)
				goto err;
			break;
		case IMAP4_STATUS:
			data = parse_status_att(view, cur);
			if (data == NULL)
				goto err;
			break;
		default:
			PARSE_ERROR("unknown untagged response");
			goto err;
		}
	}
	EXPECTS("\r\n");

	resp = PyStructSequence_New(&UntaggedResponseType);
	if (resp == NULL)
		goto err;
	PyStructSequence_SET_ITEM(resp, 0, type);
	PyStructSequence_SET_ITEM(resp, 1, data);
	return resp;

err:
	Py_XDECREF(resp);
	Py_XDECREF(type);
	Py_XDECREF(data);
	return NULL;
}

/*
 * response-tagged - returns TaggedResponse
 */
static PyObject *
parse_response_tagged(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *resp = NULL;
	PyObject *tag = NULL;
	PyObject *type = NULL;
	PyObject *text = NULL;
	long token;

	/* tag */
	tag = parse_cspn(view, cur, tag_reject);
	if (tag == NULL)
		goto err;
	EXPECTC(' ');

	/* resp-cond-state */
	token = parse_token(view, cur);
	if (token < 0)
		goto err;
	switch (token) {
	case IMAP4_OK:
	case IMAP4_NO:
	case IMAP4_BAD:
		EXPECTC(' ');
		type = Token_FromLong(token);
		if (type == NULL)
			goto err;
		text = parse_resp_text(view, cur);
		if (text == NULL)
			goto err;
		break;
	default:
		PARSE_ERROR("unknown tagged response");
		goto err;
	}
	EXPECTS("\r\n");

	resp = PyStructSequence_New(&TaggedResponseType);
	if (resp == NULL)
		goto err;
	PyStructSequence_SET_ITEM(resp, 0, tag);
	PyStructSequence_SET_ITEM(resp, 1, type);
	PyStructSequence_SET_ITEM(resp, 2, text);
	return resp;
	
err:
	Py_XDECREF(resp);
	Py_XDECREF(tag);
	Py_XDECREF(type);
	Py_XDECREF(text);
	return NULL;
}
/*
 * resp-text - returns ResponseText
 */
static PyObject *
parse_resp_text(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *resp_text = NULL;
	PyObject *text = NULL;
	PyObject *code = NULL;
	PyObject *code_data = NULL;
	char *atom;
	Py_ssize_t atom_len;
	long token;

	if (PEEKC() == '[') {
		/* resp-text-code */
		GETC();
		if (bufcspn(view, cur, atom_specials, &atom, &atom_len) < 0)
			goto err;
		if (atom_len == 0) {
			PARSE_ERROR("empty atom");
			goto err;
		}
		token = imap4_token(atom, atom_len);
		switch (token) {
		case IMAP4_ALERT:
		case IMAP4_PARSE:
		case IMAP4_READ_ONLY:
		case IMAP4_READ_WRITE:
		case IMAP4_TRYCREATE:
			code = Token_FromLong(token);
			if (code == NULL)
				goto err;
			Py_INCREF(Py_None);
			code_data = Py_None;
			break;
		case IMAP4_HIGHESTMODSEQ:
		case IMAP4_UIDNEXT:
		case IMAP4_UIDVALIDITY:
		case IMAP4_UNSEEN:
			code = Token_FromLong(token);
			if (code == NULL)
				goto err;
			EXPECTC(' ');
			code_data = parse_number(view, cur);
			if (code_data == NULL)
				goto err;
			break;
		default:
			code = PyUnicode_FromStringAndSize(atom, atom_len);
			if (code == NULL)
				goto err;
			if (PEEKC() == ' ') {
				GETC();
				code_data = parse_cspn(view, cur, resp_text_code_reject);
				if (code_data == NULL)
					goto err;
			} else {
				Py_INCREF(Py_None);
				code_data = Py_None;
			}
			break;
		}
		EXPECTC(']');

		if (PEEKC() == ' ') {
			GETC();
			text = parse_cspn(view, cur, text_reject);
			if (text == NULL)
				goto err;
		} else {
			/*
			 * The ABNF doesn't seem to allow this case, but Gmail
			 * does it.
			 */
			Py_INCREF(Py_None);
			text = Py_None;
		}
	} else {
		text = parse_cspn(view, cur, text_reject);
		if (text == NULL)
			goto err;
		Py_INCREF(Py_None);
		code = Py_None;
		Py_INCREF(Py_None);
		code_data = Py_None;
	}

	resp_text = PyStructSequence_New(&ResponseTextType);
	if (resp_text == NULL)
		goto err;
	PyStructSequence_SET_ITEM(resp_text, 0, text);
	PyStructSequence_SET_ITEM(resp_text, 1, code);
	PyStructSequence_SET_ITEM(resp_text, 2, code_data);
	return resp_text;

err:
	Py_XDECREF(resp_text);
	Py_XDECREF(text);
	Py_XDECREF(code);
	Py_XDECREF(code_data);
	return NULL;
}

/*
 * *(SP nz-number)
 */
static PyObject *
parse_search_att(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *data = NULL;

	data = PySet_New(NULL);
	if (data == NULL)
		goto err;
	while (PEEKC() == ' ') {
		PyObject *number;

		GETC();
		number = parse_number(view, cur);
		if (number == NULL)
			goto err;
		if (PySet_Add(data, number) < 0) {
			Py_DECREF(number);
			goto err;
		}
		Py_DECREF(number);
	}

	return data;

err:
	Py_XDECREF(data);
	return NULL;
}

static PyObject *
parse_sequence_set(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *list = NULL;

	list = PyList_New(0);
	if (list == NULL)
		goto err;
	while (1) {
		PyObject *item;
		unsigned long long number1, number2;

		if (_parse_number(view, cur, &number1) < 0)
			goto err;
		if (PEEKC() == ':') {
			GETC();
			if (_parse_number(view, cur, &number2) < 0)
				goto err;
			item = Py_BuildValue("KK", number1, number2);
		} else {
			item = PyLong_FromUnsignedLongLong(number1);
		}
		if (item == NULL)
			goto err;
		if (PyList_Append(list, item) < 0) {
			Py_DECREF(item);
			goto err;
		}
		Py_DECREF(item);
		if (PEEKC() != ',')
			break;
		GETC();
	}

	return list;

err:
	Py_XDECREF(list);
	return NULL;
}

/*
 * SP mailbox SP status-att-list
 */
static PyObject *
parse_status_att(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *data = NULL;
	PyObject *mailbox = NULL;
	PyObject *list = NULL;

	EXPECTC(' ');
	mailbox = parse_mailbox(view, cur);
	if (mailbox == NULL)
		goto err;
	EXPECTS(" (");

	/* status-att-list */
	list = PyDict_New();
	if (list == NULL)
		goto err;
	while (1) {
		PyObject *value;
		long token;

		token = parse_token(view, cur);
		if (token < 0)
			goto err;
		switch (token) {
		case IMAP4_MESSAGES:
		case IMAP4_RECENT:
		case IMAP4_UIDNEXT:
		case IMAP4_UIDVALIDITY:
		case IMAP4_UNSEEN:
			break;
		default:
			PARSE_ERROR("unknown status item");
			goto err;
		}
		EXPECTC(' ');
		value = parse_number(view, cur);
		if (value == NULL)
			goto err;
		if (PyDict_SetItemToken(list, token, value) < 0) {
			Py_DECREF(value);
			goto err;
		}
		Py_DECREF(value);
		if (PEEKC() != ' ')
			break;
		GETC();
	}
	EXPECTC(')');

	data = PyStructSequence_New(&StatusType);
	if (data == NULL)
		goto err;
	PyStructSequence_SET_ITEM(data, 0, mailbox);
	PyStructSequence_SET_ITEM(data, 1, list);
	return data;

err:
	Py_XDECREF(data);
	Py_XDECREF(mailbox);
	Py_XDECREF(list);
	return NULL;
}

static PyObject *
parse_string(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *bytes = NULL;
	char c;

	c = GETC();
	if (c == '"') {
		/* quoted */
		Py_ssize_t length = 0;
		char *start, *end, *p;
		char *buffer;
		Py_ssize_t capacity;

		bytes = PyBytes_FromStringAndSize(NULL, 16);
		if (bytes == NULL)
			goto err;
		if (PyBytes_AsStringAndSize(bytes, &buffer, &capacity) < 0)
			goto err;

		start = &((char *)view->buf)[*cur];
		end = &((char *)view->buf)[view->len];
		p = start;
		while ((p != end) && *p != '"') {
			if (*p == '\\') {
				p++;
				if (p == end) {
					TRUNCATED_PARSE();
					goto err;
				}
				if (*p != '"' && *p != '\\') {
					PARSE_ERROR("invalid quoted character");
					goto err;
				}
			}
			if (length >= capacity) {
				if (_PyBytes_Resize(&bytes, capacity * 2) < 0)
					goto err;
				if (PyBytes_AsStringAndSize(bytes, &buffer, &capacity) < 0)
					goto err;
			}
			buffer[length++] = *p++;
		}
		if (p == end) {
			TRUNCATED_PARSE();
			goto err;
		}
		if (_PyBytes_Resize(&bytes, length) < 0)
			goto err;
		*cur += p - start;
		EXPECTC('"');
	} else if (c == '{') {
		/* literal */
		unsigned long long number;
		Py_ssize_t length;

		if (_parse_number(view, cur, &number) < 0)
			goto err;
		if (number > PY_SSIZE_T_MAX) {
			PARSE_ERROR("literal length overflowed");
			goto err;
		}
		EXPECTS("}\r\n");
		length = (Py_ssize_t)number;

		if (view->len - *cur < length) {
			TRUNCATED_PARSE();
			goto err;
		}

		bytes = PyBytes_FromStringAndSize(&((char *)view->buf)[*cur], length);
		if (bytes == NULL)
			goto err;
		*cur += length;
	} else {
		PARSE_ERROR("invalid string");
		goto err;
	}

	return bytes;

err:
	Py_XDECREF(bytes);
	return NULL;
}

/*
 * Returns str
 */
static inline PyObject *
parse_string_ascii(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *bytes;
	PyObject *str;

	bytes = parse_string(view, cur);
	if (bytes == NULL)
		return NULL;
	str = PyUnicode_FromEncodedObject(bytes, "ascii", "strict");
	Py_DECREF(bytes);
	return str;
}

/*
 * Returns str
 */
static inline PyObject *
parse_string_ascii_lower(Py_buffer *view, Py_ssize_t *cur)
{
	PyObject *bytes;
	PyObject *lower;
	PyObject *str;

	bytes = parse_string(view, cur);
	if (bytes == NULL)
		return NULL;
	lower = PyObject_CallMethod(bytes, "lower", "()");
	Py_DECREF(bytes);
	if (lower == NULL)
		return NULL;
	str = PyUnicode_FromEncodedObject(lower, "ascii", "strict");
	Py_DECREF(lower);
	return str;
}
