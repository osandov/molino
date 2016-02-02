#include <Python.h>

#include "parser.h"

static struct PyMethodDef parser_methods[] = {
	{"parse_response_line", (PyCFunction)parse_response_line, METH_O,
	 "Parse an IMAP response"},
	{"parse_imap_string", (PyCFunction)parse_imap_string, METH_O,
	 "Parse an IMAP string"},
	{"parse_imap_astring", (PyCFunction)parse_imap_astring, METH_O,
	 "Parse an IMAP astring"},
	{NULL}
};

static struct PyModuleDef parser_module = {
	PyModuleDef_HEAD_INIT,
	"parser",
	NULL,
	-1,
	parser_methods,
};

PyMODINIT_FUNC
PyInit_parser(void)
{
	PyObject *m;

	ScannerType.tp_new = PyType_GenericNew;
	if (PyType_Ready(&ScannerType) < 0)
		return NULL;

	m = PyModule_Create(&parser_module);
	if (m == NULL)
		return NULL;

	if (imapparser_add_parser_types(m) < 0)
		return NULL;

	Py_INCREF(&ScannerType);
	PyModule_AddObject(m, "IMAPScanner", (PyObject *)&ScannerType);

	ScanError = PyErr_NewException("imap4.parser.ScanError", NULL, NULL);
	Py_INCREF(ScanError);
	PyModule_AddObject(m, "ScanError", ScanError);

	ParseError = PyErr_NewException("imap4.parser.ParseError", NULL, NULL);
	Py_INCREF(ParseError);
	PyModule_AddObject(m, "ParseError", ParseError);

	return m;
}
