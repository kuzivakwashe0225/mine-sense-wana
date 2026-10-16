<#import "template.ftl" as layout>
<#assign setsPassword = requiredActions?? && requiredActions?seq_contains("UPDATE_PASSWORD")>
<@layout.emailLayout title=setsPassword?then("Choose your Wana password", "Confirm your Wana account")
    button=setsPassword?then("Choose my password", "Confirm my email") link=link
    note="This link works once and expires in ${linkExpirationFormatter(linkExpiration)}. If you did not ask for a Wana account, ignore this email and nothing will happen.">
  <p style="margin:0 0 10px">Hello${(user.firstName?has_content)?then(" " + user.firstName, "")},</p>
  <#if setsPassword>
    <p style="margin:0">Your MineSense Wana account for <b>${user.email}</b> is ready. Open the link to confirm this address and choose your password. Then you can send field records and follow what the geologist decides.</p>
  <#else>
    <p style="margin:0">Open the link to confirm <b>${user.email}</b> for your MineSense Wana account.</p>
  </#if>
</@layout.emailLayout>
