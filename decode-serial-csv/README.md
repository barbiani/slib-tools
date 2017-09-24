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
program and can feed data directly to `generate-call-sequence` if required. With
little work, the tool can also decode MOSI-based SPI transfers (please see XXX
for details).

Canonical URL for project:
https://github.com/majava3000/slib-tools/tree/master/decode-serial-csv

# Limitations

Should be fixed first:

* The tool needlessly buffers data, while it could work as a low-buffer filter.
  Implementing the peeking facility will be become interesting (now we can side-
  step it by making a shallow copy).
* Review the calculations in ChannelCursor when time scale is large and
  increments are very small (long file, with very high UART bitrates)
* Allow inversion of signal
* Allow specifying whether STOP is inverted (might help in SPI cases)
* If the latency between queue submission and on-wire first bit is fixed, then
  allow for back-adjusting the emitted timestamp (or just allow user to specify
  the necessary adjustment in seconds to generated timestamps)

Development ideas:

* Implement autobaud when bitrate is constant (like now)
* Implement automatic baud-regions (perhaps emitted code-based, otherwise
  difficult to do without heuristics breaking, unless msb will be clear as well,
  limiting the codespace).
* The decoder uses a single (mid-point) sampling based method. Should be
  extended to N-samples with M-majority
* Add generic signal deglitcher (needs to be peekable with configurable
  de-glitch period)
* Add support for PARITY (both variants)
* Add support for multiple STOP bits

# Use cases and examples

For now, please see the XXXX for an article covering the use of this tool.
`testdata/` contains some example files that can be used for testing and
verification.

# Dependencies

The program should run equally in python 2 and python 3 environments and has no
dependencies outside the python standard library. The program should also run
equally well in non-UNIX environments, although main development is done on a
Linux desktop.

# Contributing

Contributions are appreciated, please use the canonical project URL for issues
and pull-requests. This tool is released under the GPLv3 license (please see the
included `LICENSE` file for details). Contributions do not require a CLA.
