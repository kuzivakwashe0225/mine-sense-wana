<#macro emailLayout title="" button="" link="" note="">
<html lang="${locale.language}">
<body style="margin:0;padding:0;background:#F0F4F1;font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#141B19">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F0F4F1;padding:32px 12px">
  <tr><td align="center">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border:1px solid #D2D8D2;border-radius:16px">
      <tr><td style="background:#123F31;border-radius:16px 16px 0 0;padding:22px 28px;color:#ffffff;font-size:20px;font-weight:700">
        MineSense <span style="color:#7FE0B8">Wana</span></td></tr>
      <tr><td style="padding:28px">
        <#if title?has_content><h1 style="margin:0 0 14px;font-size:22px">${title}</h1></#if>
        <div style="font-size:15px;line-height:1.6"><#nested></div>
        <#if link?has_content>
          <p style="margin:24px 0"><a href="${link}" style="display:inline-block;background:#1E7A4F;color:#ffffff;text-decoration:none;font-weight:700;padding:12px 22px;border-radius:9px">${button}</a></p>
          <p style="font-size:12.5px;color:#5A6661;word-break:break-all">If the button does not work, copy this address into your browser:<br>${link}</p>
        </#if>
        <#if note?has_content><p style="font-size:13px;color:#5A6661">${note}</p></#if>
      </td></tr>
      <tr><td style="padding:16px 28px;border-top:1px solid #D2D8D2;font-size:12px;color:#5A6661">
        Wana shows places worth checking. It does not prove a resource and gives no mining rights.</td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>
</#macro>
