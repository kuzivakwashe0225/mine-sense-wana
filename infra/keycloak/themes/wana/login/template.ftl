<#-- MineSense Wana layout for every Keycloak page (log in, choose password, reset, verify email, info, errors).
     Same structure as base/template.ftl, arranged as: form on the left, contour-map panel on the right. -->
<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false>
<!DOCTYPE html>
<html class="${properties.kcHtmlClass!}" lang="${lang}">
<head>
    <meta charset="utf-8">
    <meta name="robots" content="noindex, nofollow">
    <#if properties.meta?has_content>
        <#list properties.meta?split(' ') as meta>
            <meta name="${meta?split('==')[0]}" content="${meta?split('==')[1]}"/>
        </#list>
    </#if>
    <title>${msg("loginTitle",(realm.displayName!''))}</title>
    <link rel="icon" type="image/svg+xml" href="${url.resourcesPath}/img/hero.svg" />
    <#list properties.styles?split(' ') as style>
        <link href="${url.resourcesPath}/${style}" rel="stylesheet" />
    </#list>
    <script type="importmap">{ "imports": { "rfc4648": "${url.resourcesCommonPath}/vendor/rfc4648/rfc4648.js" } }</script>
    <#if scripts??><#list scripts as script><script src="${script}" type="text/javascript"></script></#list></#if>
    <script type="module">
        import { startSessionPolling } from "${url.resourcesPath}/js/authChecker.js";
        startSessionPolling("${url.ssoLoginInOtherTabsUrl?no_esc}");
    </script>
    <#if authenticationSession??>
        <script type="module">
            import { checkAuthSession } from "${url.resourcesPath}/js/authChecker.js";
            checkAuthSession("${authenticationSession.authSessionIdHash}");
        </script>
    </#if>
</head>
<body class="${properties.kcBodyClass!} ${bodyClass}" data-page-id="login-${pageId}">
<div class="auth">
  <main class="auth-form">
    <div class="auth-inner">
      <#assign appUrl = (client?? && client.baseUrl?has_content)?then(client.baseUrl, "")>
      <a class="auth-brand" <#if appUrl?has_content>href="${appUrl}"</#if>>
        <span class="logo" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M6 24 13 9l5 9 3-5 5 11z" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"/><circle cx="21" cy="13" r="2.6" fill="#E58456"/></svg></span>
        <span>MineSense <b>Wana</b></span>
      </a>

      <#if !(auth?has_content && auth.showUsername() && !auth.showResetCredentials())>
        <h1 id="kc-page-title" class="auth-title"><#nested "header"></h1>
        <#if pageId == "login.ftl"><p class="auth-sub">${msg("wanaTagline")}</p></#if>
      <#else>
        <#nested "show-username">
        <h1 id="kc-page-title" class="auth-title"><#nested "header"></h1>
        <div id="kc-username" class="username-chip">
          <span class="wi wi-person" aria-hidden="true"></span>
          <label id="kc-attempted-username">${auth.attemptedUsername}</label>
          <a id="reset-login" href="${url.loginRestartFlowUrl}" aria-label="${msg("restartLoginTooltip")}"><span class="wi wi-arrow-repeat" aria-hidden="true"></span></a>
        </div>
      </#if>

      <section class="auth-card">
        <#if displayMessage && message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
          <div class="${properties.kcAlertClass!} walert-${message.type}" role="alert">
            <span class="wi wi-${message.type}" aria-hidden="true"></span>
            <span class="${properties.kcAlertTitleClass!}">${kcSanitize(message.summary)?no_esc}</span>
          </div>
        </#if>

        <#nested "form">

        <#if auth?has_content && auth.showTryAnotherWayLink()>
          <form id="kc-select-try-another-way-form" action="${url.loginAction}" method="post">
            <input type="hidden" name="tryAnotherWay" value="on"/>
            <a href="#" id="try-another-way" onclick="document.forms['kc-select-try-another-way-form'].requestSubmit();return false;">${msg("doTryAnotherWay")}</a>
          </form>
        </#if>

        <#nested "socialProviders">

        <#if displayInfo><div id="kc-info" class="auth-info"><#nested "info"></div></#if>

        <#if pageId == "login.ftl" && appUrl?has_content>
          <p class="auth-foot">${msg("wanaNoAccount")} <a href="${appUrl}#signup">${msg("wanaCreateAccount")}</a></p>
        </#if>
      </section>

      <#if appUrl?has_content><a class="auth-back" href="${appUrl}"><span class="wi wi-arrow-left" aria-hidden="true"></span> ${msg("wanaBack")}</a></#if>
      <p class="auth-legal">${msg("wanaNoRights")}</p>
    </div>
  </main>
  <aside class="auth-hero" aria-hidden="true">
    <img src="${url.resourcesPath}/img/hero.svg" alt=""/>
    <div class="glass">
      <h2>${msg("wanaHeroTitle")}</h2>
      <p>${msg("wanaHeroText")}</p>
      <ul>
        <li><span class="wi wi-check"></span>${msg("wanaPoint1")}</li>
        <li><span class="wi wi-check"></span>${msg("wanaPoint2")}</li>
        <li><span class="wi wi-check"></span>${msg("wanaPoint3")}</li>
        <li><span class="wi wi-check"></span>${msg("wanaPoint4")}</li>
      </ul>
    </div>
  </aside>
</div>
</body>
</html>
</#macro>
