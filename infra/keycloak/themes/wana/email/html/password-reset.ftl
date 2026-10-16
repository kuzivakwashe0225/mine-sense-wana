<#import "template.ftl" as layout>
<@layout.emailLayout title="Reset your Wana password" button="Choose a new password" link=link
    note="This link expires in ${linkExpirationFormatter(linkExpiration)}. If you did not ask for this, ignore this email; your password stays the same.">
  <p style="margin:0">Someone asked to reset the password for <b>${user.email}</b> on MineSense Wana. If it was you, open the link below.</p>
</@layout.emailLayout>
