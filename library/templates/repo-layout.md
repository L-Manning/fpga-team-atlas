# FPGA project repository layout

> [!note] Draft in review. Example content for the atlas prototype.

```text
<design>/
├── rtl/            VHDL sources, one entity per file
├── sim/            testbenches, run scripts and expected results
├── constraints/    XDC files: timing, pinout, physical
├── ip/             vendor IP configuration (.xci), never generated outputs
├── scripts/        build and simulation scripts (Tcl, Python)
├── docs/           design description and interface notes
└── README.md       what this is, how to build it, who owns it
```

Generated files (runs, caches, bitstreams) are never committed. CI publishes them as build artefacts instead.
