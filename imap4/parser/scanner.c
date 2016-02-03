#include <Python.h>

#include "parser.h"

PyObject *ScanError;

typedef struct {
	PyObject_HEAD
	char *buf;
	size_t buflen;
	size_t bufcap;
	size_t start_find;
	size_t literal_left;
} Scanner;

static void
Scanner_dealloc(Scanner *self)
{
	PyMem_RawFree(self->buf);
	Py_TYPE(self)->tp_free((PyObject *)self);
}

static PyObject *
Scanner_feed(Scanner *self, PyObject *args)
{
	PyObject *buf, *len_obj = NULL;
	Py_ssize_t len;
	Py_buffer view;
	char *newbuf;

	if (!PyArg_ParseTuple(args, "O|O", &buf, &len_obj))
		return NULL;

	if (PyObject_GetBuffer(buf, &view, PyBUF_SIMPLE) < 0)
		return NULL;
	if (len_obj == NULL)
		len = view.len;
	else
		len = PyLong_AsSsize_t(len_obj);
	if (len > view.len) {
		len = view.len;
	} else if (len < 0) {
		if (len < -view.len)
			len = 0;
		else
			len = view.len + len;
	}

	self->buflen += len;
	if (self->buflen > self->bufcap) {
		newbuf = PyMem_RawRealloc(self->buf, self->buflen);
		if (newbuf == NULL) {
			PyBuffer_Release(&view);
			return PyErr_NoMemory();
		}
		self->buf = newbuf;
		self->bufcap = self->buflen;
	}

	memcpy(&self->buf[self->buflen - len], view.buf, len);
	PyBuffer_Release(&view);
	Py_RETURN_NONE;
}

static PyObject *
Scanner_get(Scanner *self)
{
	char *crlf;

	while (1) {
		if (self->literal_left > 0) {
			size_t n = self->buflen - self->start_find;
			if (n < self->literal_left) {
				self->start_find += n;
				self->literal_left -= n;
				PyErr_SetString(ScanError, "incomplete literal");
				return NULL;
			} else {
				self->start_find += self->literal_left;
				self->literal_left = 0;
			}
		}

		crlf = memmem(self->buf + self->start_find,
			      self->buflen - self->start_find, "\r\n", 2);
		if (!crlf) {
			if (self->buflen > 0)
				self->start_find = self->buflen - 1;
			PyErr_SetString(ScanError, "incomplete line");
			return NULL;
		}

		if (crlf != self->buf && *(crlf - 1) == '}') {
			char *p = crlf - 1;
			unsigned long length;

			while (p > self->buf && isdigit(*(p - 1)))
				p--;
			if (p == self->buf || *(p - 1) != '{' || p == crlf - 1)
				break;
			errno = 0;
			length = strtoul(p, NULL, 10);
			if (errno)
				return PyErr_SetFromErrno(ScanError);
			self->literal_left = length;
			self->start_find = crlf - self->buf + 2;
		} else {
			break;
		}
	}

	/*
	 * If this is called twice in a row, make it so we can find the CRLF
	 * right away.
	 */
	self->start_find = crlf - self->buf;

	/*
	 * XXX: If the memoryview is accessed after the scanner is freed, the
	 * memoryview will refer to freed memory.
	 */
	return PyMemoryView_FromMemory(self->buf, crlf - self->buf + 2, PyBUF_READ);
}

static PyObject *
Scanner_consume(Scanner *self, PyObject *n_obj)
{
	size_t n;

	n = PyLong_AsSize_t(n_obj);
	if (PyErr_Occurred())
		return NULL;
	if (n > self->buflen) {
		PyErr_SetString(ScanError, "consuming too many characters");
		return NULL;
	}

	self->buflen -= n;
	memmove(self->buf, &self->buf[n], self->buflen);
	self->start_find = 0;
	self->literal_left = 0;
	Py_RETURN_NONE;
}

static PyMethodDef Scanner_methods[] = {
	{"feed", (PyCFunction)Scanner_feed, METH_VARARGS,
	 "Feed a buffer to the scanner"},
	{"get", (PyCFunction)Scanner_get, METH_NOARGS,
	 "Get a line from the scanner"},
	{"consume", (PyCFunction)Scanner_consume, METH_O,
	 "Consume the given number of characters from the scanner"},
	{NULL}
};

PyTypeObject ScannerType = {
	PyVarObject_HEAD_INIT(NULL, 0)
	"imap4.parser.IMAPScanner",	/* tp_name */
	sizeof(Scanner),		/* tp_basicsize */
	0,				/* tp_itemsize */
	(destructor)Scanner_dealloc,	/* tp_dealloc */
	0,				/* tp_print */
	0,				/* tp_getattr */
	0,				/* tp_setattr */
	0,				/* tp_reserved */
	0,				/* tp_repr */
	0,				/* tp_as_number */
	0,				/* tp_as_sequence */
	0,				/* tp_as_mapping */
	0,				/* tp_hash  */
	0,				/* tp_call */
	0,				/* tp_str */
	0,				/* tp_getattro */
	0,				/* tp_setattro */
	0,				/* tp_as_buffer */
	Py_TPFLAGS_DEFAULT,		/* tp_flags */
	"IMAP scanner",			/* tp_doc */
	0,				/* tp_traverse */
	0,				/* tp_clear */
	0,				/* tp_richcompare */
	0,				/* tp_weaklistoffset */
	0,				/* tp_iter */
	0,				/* tp_iternext */
	Scanner_methods,		/* tp_methods */
};
