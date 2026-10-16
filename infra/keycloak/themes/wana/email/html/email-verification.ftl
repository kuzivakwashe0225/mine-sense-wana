<#import "template.ftl" as layout>
<@layout.emailLayout title="Confirm your email" button="Confirm my email" link=link
    note="This link expires in ${linkExpirationFormatter(linkExpiration)}. If you did not create a Wana account, ignore this email.">
  <p style="margin:0">Open the link to confirm <b>${user.email}</b> for your MineSense Wana account.</p>
</@layout.emailLayout>
