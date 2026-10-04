CERTIKEEP FONT SETUP

This project now supports two local custom fonts:

1) Logo font (used only for the CertiKeep wordmark)
   Put ONE of these files here:
   - certikeep-logo.otf
   - certikeep-logo.ttf

2) UI font (used everywhere else in the website)
   Put ONE of these files here:
   - certikeep-ui.otf
   - certikeep-ui.ttf

You only need one extension for each font. OTF or TTF both work.

After changing a font file, restart Vite if the browser does not refresh it automatically:
    npm run dev

If you change the filenames, update the two @font-face blocks at the top of:
    frontend/src/styles.css
