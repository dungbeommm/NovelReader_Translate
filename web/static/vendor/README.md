# Material Color Utilities

`material-color-utilities.js` is a self-hosted IIFE bundle of Google's
`@material/material-color-utilities` 0.4.0, licensed under Apache 2.0
(see `material-color-utilities.LICENSE`). It exports `MaterialColors` with
`Hct`, `SchemeTonalSpot`, `SchemeMonochrome`, `MaterialDynamicColors`,
`TonalPalette`, `argbFromHex` and `hexFromArgb`.

Source: https://github.com/material-foundation/material-color-utilities

Build an entry exporting those symbols from the package with esbuild:
`esbuild entry.js --bundle --minify --format=iife --global-name=MaterialColors --outfile=material-color-utilities.js`.
The production app uses local assets and makes no color-library CDN requests.
