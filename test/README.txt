ANBA BISHOY - SHARED IMAGE BRANDING
=================================
This is an add-on for the Django project discussed in this chat.
It uses the supplied composite image unchanged. No separate saint image
has been supplied; that slot is intentionally disabled.

INSTALL
1. Back up accounts/templates/accounts/base.html and
   kitchen/templates/kitchen/dashboard.html.
2. Merge the package folders into the project folder containing manage.py.
   Copy the files; do not delete or replace whole application directories.
3. Add this ONE string to the existing TEMPLATES -> OPTIONS ->
   context_processors list in api/settings.py:
       "core.site_branding.monastery_branding",
4. Add MONASTERY_BRANDING from settings_additions.txt to api/settings.py.
   Leave saint_image empty until the actual second image is available.
5. Keep the existing five burgundy CSS files and static/js/simple_ui.js.
   This package adds monastery_branding.css and monastery_branding.js;
   it does not replace the previous theme or ordering JavaScript.
6. Run:
       python manage.py check
       python manage.py findstatic images/branding/monastery.jpg
       python manage.py runserver

REPLACED FILES
- base.html is based on the shared base template last provided in the chat.
  If you added other custom blocks or integrations locally, merge those
  edits rather than discarding them.
- dashboard.html is the existing supplied report template plus the report
  image include and two layout classes. Filters and grouping are retained.

NEW FILES
- core/site_branding.py: shared image paths; no database queries.
- accounts/templates/accounts/includes/branding_photos.html
- accounts/templates/accounts/includes/branding_splash.html
- accounts/templates/accounts/includes/report_branding.html
- static/css/monastery_branding.css
- static/js/monastery_branding.js
- static/images/branding/monastery.jpg: byte-for-byte copy of the upload.

BEHAVIOR
- A compact permanent photo in the shared application header.
- A welcome screen on first entry in a fresh tab session and on real reload.
  Regular internal navigation does not replay it while the tab's state is
  available. Duration defaults to about 1.5 seconds after image decoding;
  a hard safety deadline avoids blocking the page if the image is slow.
- Skip via the button or Escape. No sound. Reduced motion is respected.
- JavaScript failure/disabled JavaScript: no modal, header and report remain.
- No new unload or beforeunload listeners. No changes to filters or forms.
- The report gets an image in its report-header. The opening screen and
  application header are not printed. The picture appears once in the
  report masthead, not behind table text or repeated per order.
- Only pages extending accounts/base.html receive the shared application
  header. The built-in /admin/ interface is not changed by this add-on.

SECOND PHOTO
Copy the actual separate image to static/images/branding/saint-bishoy.jpg,
then change only this setting in MONASTERY_BRANDING:
    "saint_image": "images/branding/saint-bishoy.jpg",
The same include renders the two images in the header, splash and report.
Do not set a filename before supplying the file.

NO SCHEMA CHANGES
No models, view business logic, sessions storing report filters, user roles,
order rows, migrations or URLs are changed. No Django Admin registration
is needed for these fixed site-identity assets.

PRINT
Use A4, Color and Background graphics in the browser print dialog.
The existing colored dashboard.css must remain installed.
Wait for the report image to be visible before printing.
The photograph is shown intact with object-fit: contain; it is not cropped
into a circle, regenerated or used as a background beneath the order text.

VALIDATION SCOPE
Python AST syntax, JS syntax, CSS parse and Django block balance checked.
Offline Chromium fixtures checked for header images, opening/closing,
Skip/Escape, mobile width, print color/image and four filter options.
Navigation type and tab storage were simulated in those fixtures.
The actual Django installation and the user's database were not executed.
Preview screenshots contain illustrative data only.

PRIMARY REFERENCES
https://docs.djangoproject.com/en/6.1/howto/static-files/
https://docs.djangoproject.com/en/6.1/ref/templates/api/
https://developer.mozilla.org/en-US/docs/Web/API/PerformanceNavigationTiming/type
https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage
https://developer.mozilla.org/en-US/docs/Web/API/HTMLDialogElement/showModal
https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/print-color-adjust
