// Deployment settings for the click-through signing page.
window.NDA_CONFIG = {
  // Where the signed copy should be emailed if the page is used without the server
  // (static hosting or as an attachment). Set this to your own address.
  returnEmail: "mhuberty@gspartners.com",
  returnName: "Matt Huberty",
  // Where the signed record is delivered automatically.
  //   "/api/sign"  = the bundled server.py (when the page is served by it)
  //   "https://script.google.com/macros/s/…/exec" = the Google Apps Script receiver in apps-script/Code.gs
  //   ""           = no automatic delivery; the signer emails the PDF (share sheet on phones, mailto on desktop)
  submitUrl: "/api/sign",
  // Display name for the GSP signer on the countersignature page (optional prefill).
  gspSigner: { name: "", title: "" }
};
