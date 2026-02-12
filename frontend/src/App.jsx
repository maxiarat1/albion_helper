import './App.css'

import ChatWorkspace from './features/chat/ChatWorkspace'
import DataManagerPanel from './features/data/DataManagerPanel'
import GoldPricePanel from './features/gold/GoldPricePanel'
import MarketHistoryPanel from './features/market/MarketHistoryPanel'
import useAlbionConsole from './hooks/useAlbionConsole'

function App() {
  const consoleState = useAlbionConsole()

  return (
    <div className="app">
      <header>
        <h1>Albion Helper</h1>
        <p>Primitive LLM console</p>
      </header>

      <MarketHistoryPanel
        marketItem={consoleState.marketItem}
        setMarketItem={consoleState.setMarketItem}
        marketQuality={consoleState.marketQuality}
        setMarketQuality={consoleState.setMarketQuality}
        marketStartDate={consoleState.marketStartDate}
        setMarketStartDate={consoleState.setMarketStartDate}
        marketEndDate={consoleState.marketEndDate}
        setMarketEndDate={consoleState.setMarketEndDate}
        marketCities={consoleState.marketCities}
        setMarketCities={consoleState.setMarketCities}
        marketIncludeLatestApi={consoleState.marketIncludeLatestApi}
        setMarketIncludeLatestApi={consoleState.setMarketIncludeLatestApi}
        marketBusy={consoleState.marketBusy}
        marketError={consoleState.marketError}
        marketResult={consoleState.marketResult}
        fetchMarketPrices={consoleState.fetchMarketPrices}
        itemLabels={consoleState.itemLabels}
      />

      <GoldPricePanel
        goldData={consoleState.goldData}
        goldBusy={consoleState.goldBusy}
        goldError={consoleState.goldError}
        goldRange={consoleState.goldRange}
        setGoldRange={consoleState.setGoldRange}
        fetchGoldPrices={consoleState.fetchGoldPrices}
      />

      <DataManagerPanel
        dbStatus={consoleState.dbStatus}
        dbLoading={consoleState.dbLoading}
        dbUpdating={consoleState.dbUpdating}
        dbUpdateResult={consoleState.dbUpdateResult}
        dbUpdateProgress={consoleState.dbUpdateProgress}
        dbResetting={consoleState.dbResetting}
        dbResetResult={consoleState.dbResetResult}
        triggerDbUpdate={consoleState.triggerDbUpdate}
        finishDbUpdateFlow={consoleState.finishDbUpdateFlow}
        hardResetDatabase={consoleState.hardResetDatabase}
        formatNumber={consoleState.formatNumber}
      />

      <ChatWorkspace
        provider={consoleState.provider}
        setProvider={consoleState.setProvider}
        model={consoleState.model}
        handleModelChange={consoleState.handleModelChange}
        ollamaModels={consoleState.ollamaModels}
        loadingModels={consoleState.loadingModels}
        apiKeys={consoleState.apiKeys}
        handleApiKeyChange={consoleState.handleApiKeyChange}
        message={consoleState.message}
        setMessage={consoleState.setMessage}
        mcpEnabled={consoleState.mcpEnabled}
        setMcpEnabled={consoleState.setMcpEnabled}
        mcpTools={consoleState.mcpTools}
        mcpAllowed={consoleState.mcpAllowed}
        setMcpAllowed={consoleState.setMcpAllowed}
        thinkingEnabled={consoleState.thinkingEnabled}
        setThinkingEnabled={consoleState.setThinkingEnabled}
        ollamaThinkingModeType={consoleState.ollamaThinkingModeType}
        ollamaThinkingModes={consoleState.ollamaThinkingModes}
        ollamaThinkMode={consoleState.ollamaThinkMode}
        setOllamaThinkMode={consoleState.setOllamaThinkMode}
        ollamaThinkingSupported={consoleState.ollamaThinkingSupported}
        sendMessage={consoleState.sendMessage}
        busy={consoleState.busy}
        clearConversation={consoleState.clearConversation}
        conversation={consoleState.conversation}
        error={consoleState.error}
        expandedTools={consoleState.expandedTools}
        setExpandedTools={consoleState.setExpandedTools}
        itemLabels={consoleState.itemLabels}
        resolvedQueries={consoleState.resolvedQueries}
      />
    </div>
  )
}

export default App
