# Third-party notices

The repository bundles the following third-party JavaScript files so that the
web interface works without network access. Each file remains under the license of its upstream
project; the [MIT license](LICENSE) of this repository covers only the
project's own code.

The column "License statement in the file" quotes what the bundled file itself
says. Where a file carries no license statement for the package, the license of
the upstream project applies and is not restated here.

| File | Package | Version | License statement in the file |
|---|---|---|---|
| `static/vendor/cytoscape-3.28.1.min.js` | cytoscape | 3.28.1 (file name) | Banner: "Copyright (c) 2016-2023, The Cytoscape Consortium" followed by a permission notice (free use, copy, modify, merge, publish, distribute, sublicense and sale, with the notice to be kept). An embedded component states "Copyright (c) 2013-2014 Ralf S. Engelschall, Licensed under The MIT License". |
| `static/vendor/cytoscape-dagre-2.5.0.min.js` | cytoscape-dagre | 2.5.0 (file name and banner) | license per upstream project (not stated in the file) |
| `static/vendor/cytoscape-fcose-2.2.0.min.js` | cytoscape-fcose | 2.2.0 (file name) | license per upstream project (not stated in the file) |
| `static/vendor/cose-base-2.2.0.min.js` | cose-base | 2.2.0 (file name) | license per upstream project (not stated in the file) |
| `static/vendor/layout-base-2.0.1.min.js` | layout-base | 2.0.1 (file name) | The file contains the notice "Copyright: i-Vis Research Group, Bilkent University, 2007 - present" and the full text of the Apache License, Version 2.0. |
| `static/vendor/dagre-0.8.5.min.js` | dagre | 0.8.5 (file name and version string in the file) | Embedded notices: "Copyright (c) 2012-2014 Chris Pettitt" with a permission notice, and "Copyright (c) 2014, Chris Pettitt, All rights reserved" with redistribution conditions. The bundle also contains further embedded modules with their own notices. |
| `static/vendor/lucide-0.460.0.min.js` | lucide | 0.460.0 (file name and banner) | Banner: "@license lucide v0.460.0 - ISC. This source code is licensed under the ISC license." |
| `static/vendor/tailwind-play-3.4.16.min.js` | Tailwind CSS (Play CDN build) | 3.4.16 (file name) | The file emits the comment "tailwindcss v<version> \| MIT License \| https://tailwindcss.com". Embedded modules carry their own notices (for example "Copyright (c) 2014-present, Jon Schlinkert. Licensed under the MIT License."). |

Python dependencies are not bundled; they are installed from
[`requirements.txt`](requirements.txt) and keep their own licenses.
