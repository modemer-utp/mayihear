@description('Bot App Registration Client ID')
param botId string

@description('Bot App Registration Client Secret')
@secure()
param botPassword string

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('App Service Plan SKU')
param appServiceSku string = 'B1'

// ── App Service Plan ──────────────────────────────────────────────────────────
resource appServicePlan 'Microsoft.Web/serverfarms@2022-03-01' = {
  name: 'mayihear-plan'
  location: location
  sku: {
    name: appServiceSku
  }
  kind: 'linux'
  properties: {
    reserved: true  // required for Linux
  }
}

// ── App Service (Python) ──────────────────────────────────────────────────────
resource webApp 'Microsoft.Web/sites@2022-03-01' = {
  name: 'mayihear-agent'
  location: location
  kind: 'app,linux'
  properties: {
    serverFarmId: appServicePlan.id
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appCommandEntry: 'python src/app.py'
      appSettings: [
        { name: 'BOT_ID', value: botId }
        { name: 'BOT_PASSWORD', value: botPassword }
        { name: 'BOT_DOMAIN', value: '${webApp.name}.azurewebsites.net' }
        { name: 'MONDAY_BOARD_ID', value: '18405594787' }
        { name: 'GRAPH_WEBHOOK_SECRET', value: 'mayihear-secret' }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
      ]
    }
    httpsOnly: true
  }
}

// ── Azure Bot Service ─────────────────────────────────────────────────────────
resource botService 'Microsoft.BotService/botServices@2022-09-15' = {
  name: 'mayihear-bot'
  location: 'global'
  sku: {
    name: 'F0'  // Free tier: 10,000 messages/month
  }
  kind: 'azurebot'
  properties: {
    displayName: 'MayiHear'
    msaAppId: botId
    msaAppType: 'SingleTenant'
    endpoint: 'https://${webApp.properties.defaultHostName}/api/messages'
  }
}

// ── Teams Channel on Bot Service ──────────────────────────────────────────────
resource teamsChannel 'Microsoft.BotService/botServices/channels@2022-09-15' = {
  parent: botService
  name: 'MsTeamsChannel'
  properties: {
    channelName: 'MsTeamsChannel'
    properties: {
      isEnabled: true
    }
  }
}

output webAppHostName string = webApp.properties.defaultHostName
output botServiceName string = botService.name
output webhookUrl string = 'https://${webApp.properties.defaultHostName}/webhook'
