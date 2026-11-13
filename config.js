// Deployment settings for the click-through signing page.
window.NDA_CONFIG = {
  // Where the signed copy should be emailed if the page is used without the server
  // (static hosting or as an attachment). Set this to your own address.
  returnEmail: "mhuberty@gspartners.com",
  returnName: "Matt Huberty",
  // Endpoint the page posts the signed record to. Leave as-is when using server.py.
  submitUrl: "/api/sign",
  // Display name for the GSP signer on the countersignature page (optional prefill).
  gspSigner: { name: "", title: "" }
};
