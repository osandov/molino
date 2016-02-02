#ifndef IMAPPARSER_H
#define IMAPPARSER_H

extern PyTypeObject ScannerType;
extern PyObject *ScanError;
extern PyObject *ParseError;

extern PyTypeObject AddressType;
extern PyTypeObject TextBodyType;
extern PyTypeObject MessageBodyType;
extern PyTypeObject BasicBodyType;
extern PyTypeObject MultipartBodyType;
extern PyTypeObject ContinueReqType;
extern PyTypeObject EnvelopeType;
extern PyTypeObject EsearchType;
extern PyTypeObject FetchType;
extern PyTypeObject ListType;
extern PyTypeObject ResponseTextType;
extern PyTypeObject StatusType;
extern PyTypeObject TaggedResponseType;
extern PyTypeObject UntaggedResponseType;

int imapparser_add_parser_types(PyObject *module);
int imapparser_add_token_constants(PyObject *module);

long imap4_token(const char *str, Py_ssize_t len);

PyObject *parse_response_line(PyObject *self, PyObject *buf);
PyObject *parse_imap_string(PyObject *self, PyObject *buf);
PyObject *parse_imap_astring(PyObject *self, PyObject *buf);

#endif /* IMAPPARSER_H */
