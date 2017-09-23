# decode-serial

This small utility decodes the digital capture data produced by Saleae Logic
when data is exported in CSV format. From this data, the program attempts to
recognize data frames assuming specific baudrate UART has emitted the trace.

Output format of the data is also CSV, which contains event start timestamps
(in seconds), the recognized data as an unsigned number. For convenience also
printable ASCII version of data is emitted in a separate column as is the
information whether the frame was recognized properly (only STOP-bit check is
done).

The tool is useful to convert serial link data into serial event trace format
which can be decoded by `generate-call-sequence` (a separate tool located in the
same repository where this one lives). The tool runs as an "UNIX-like" filter
program and can feed data directly to `generate-call-sequence` if required.

Canonical URL for project:
https://github.com/majava3000/slib-tools/tree/master/decode-serial-csv

# Use cases and examples

For now, please see the XXXX for an article covering the use of this tool

# Dependencies

The program should run equally in python 2 and python 3 environments and has no
dependencies outside the python standard library. The program should also run
equally well in non-UNIX environments, although main development is done on a
Linux desktop.

# Contributing

Contributions are appreciated, please use the canonical project URL for issues
and pull-requests. This tool is released under the GPLv3 license (please see the
included `LICENSE` file for details).
