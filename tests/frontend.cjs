const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
// Exercise real rendering functions without starting the DOM initialization.
let src = fs.readFileSync('script.js', 'utf8').split('// ── Sidebar / hamburger / routing')[0];
const ctx = vm.createContext({ Intl, Date, Number, URL, Set });
vm.runInContext(src, ctx);
for (const [zone, instant, expected] of [
  ['Asia/Kolkata', '2026-01-15T20:00:00Z', '16 Jan 2026, 01:30:00 IST'],
  ['Asia/Singapore', '2026-01-15T20:00:00Z', '16 Jan 2026, 04:00:00 GMT+8'],
  ['America/New_York', '2026-01-15T20:00:00Z', '15 Jan 2026, 15:00:00 EST'],
  ['America/New_York', '2026-07-15T20:00:00Z', '15 Jul 2026, 16:00:00 EDT'],
  ['America/New_York', '2026-03-08T07:00:00Z', '08 Mar 2026, 03:00:00 EDT'],
]) assert.equal(ctx.quoteTime(instant, zone), expected);
assert.equal(ctx.quoteTime(null), 'Unknown quote time');
assert.equal(ctx.quoteTime('invalid'), 'Unknown quote time');
for (const [region, suffix] of [['us','EST'], ['india','IST'], ['asia','GMT+8']]) {
  const markup = ctx.renderStocksTable([{name:'Regional',ticker:'X',source_timestamp:'2026-01-15T20:00:00Z'}], region);
  assert(markup.includes(suffix));
  assert(markup.includes('Source refresh target: 5 minutes'));
}
assert.equal(vm.runInContext("formatDecimal('123.0000')", ctx), '123.0000');
assert.equal(vm.runInContext("fmtFxValue(94.475, '94.475')", ctx), '94.475');
assert.equal(vm.runInContext("fmtFxValue(94.4905, '94.4905')", ctx), '94.4905');
ctx.fxRow = {source_timestamp: new Date(Date.now()-481000).toISOString(),
  source:'Google Finance', market_status:'OPEN', validation_status:'VERIFIED',
  quote_policy:{max_quote_age_seconds:480}, quote_basis:'midpoint'};
assert(vm.runInContext('quoteStatus(fxRow)', ctx).startsWith('STALE'));
assert(vm.runInContext('quoteStatus(fxRow)', ctx).includes('Google Finance'));
ctx.fxRow.source_timestamp = new Date().toISOString();
assert(!vm.runInContext('quoteStatus(fxRow)', ctx).startsWith('STALE'));
ctx.indicative = {...ctx.fxRow, ticker:'INR=X', indexValue:94.4905, verification_version:1,
  validation_status:'INDICATIVE', quote_quality:'INDICATIVE',
  field_metadata:{indexValue:{validation_status:'INDICATIVE',decimal:'94.4905'}}};
const fxHtml = vm.runInContext('fxHeroHtml([indicative])',ctx);
assert(fxHtml.includes('1 USD = ₹94.4905'));
assert(fxHtml.includes('INDICATIVE'));
assert(!fxHtml.includes('DATA UNAVAILABLE'));
ctx.indicative.validation_status = 'STALE';
assert(vm.runInContext('fxHeroHtml([indicative])',ctx).includes('STALE · INDICATIVE'));
ctx.fieldRow = {field_metadata:{marketCap:{validation_status:'INDICATIVE',quality:'INDICATIVE',source:'Google Finance',source_timestamp:new Date().toISOString()}}};
assert(vm.runInContext("fieldStatus(fieldRow,'marketCap')",ctx).includes('INDICATIVE'));
assert(vm.runInContext("fieldStatus(fieldRow,'marketCap')",ctx).includes('Google Finance'));
assert.equal(vm.runInContext("formatDecimal('123456.123456789')", ctx), '123,456.123456789');
assert.equal(vm.runInContext('fmtGainLossPercent(null)', ctx), 'DATA UNAVAILABLE');
assert.equal(vm.runInContext("safeNewsUrl('javascript:alert(1)')", ctx), '#');
assert.equal(vm.runInContext("fmtGainLossPercent(0, '0.0000')", ctx), '0.0000%');
const html = vm.runInContext("renderStocksTable([{name:'Legacy',ticker:'X',marketCap:123,indexValue:1,changePercent:null}], 'us')", ctx);
assert(html.includes('Legacy'));
assert(html.includes('DATA UNAVAILABLE'));
assert(!html.includes('0.00%'));
ctx.gold = {name:'Gold',ticker:'GC=F',unit:'USD/troy oz',indexValue:3110.34768,
  verification_version:1,validation_status:'INDICATIVE',
  field_metadata:{indexValue:{validation_status:'INDICATIVE',decimal:'3110.34768'}}};
ctx.inr = { ...ctx.indicative,base_currency:'USD',quote_currency:'INR',indexValue:94.49,
  field_metadata:{indexValue:{validation_status:'INDICATIVE',decimal:'94.49'}}};
const goldDisplay = vm.runInContext('commodityDisplay(gold,inr)',ctx);
ctx.localGold = {name:'Gold (24 Carat, Hyderabad)',ticker:'GOLD_24K_HYDERABAD',unit:'INR/gram',
  source:'Groww',source_date:'2026-09-15',source_timestamp:new Date().toISOString(),
  indexValue:14742,verification_version:1,validation_status:'INDICATIVE',
  field_metadata:{indexValue:{validation_status:'INDICATIVE',decimal:'14742',source:'Groww'}}};
assert.equal(vm.runInContext('commodityDisplay(localGold).rate',ctx),'₹14,742');
assert.equal(vm.runInContext('commodityDisplay(localGold,inr).rate',ctx),'₹14,742');
assert.equal(vm.runInContext("marketReference(localGold,'indexValue',inr)",ctx),'Groww');
const localGoldHtml = vm.runInContext("renderStocksTable([localGold], 'commodities')",ctx);
assert(localGoldHtml.includes('Gold (24 Carat, Hyderabad)'));
assert(localGoldHtml.includes('As of 2026-09-15'));
assert(localGoldHtml.includes('Excludes GST'));
assert(localGoldHtml.includes('https://groww.in/gold-rates/gold-rate-today-in-hyderabad'));
ctx.localGold.validation_status = 'STALE';
assert(vm.runInContext('commodityDisplay(localGold).note',ctx).includes('STALE'));
ctx.localGold.indexValue = null;
assert.equal(vm.runInContext('commodityDisplay(localGold,inr).rate',ctx),'DATA UNAVAILABLE');
assert.equal(goldDisplay.quantity,'1 Grm');
assert.equal(goldDisplay.rate,'≈ ₹9,449.00');
assert(goldDisplay.title.includes('31.1034768'));
ctx.silver={...ctx.gold,name:'Silver',ticker:'SI=F',indexValue:31.1034768,
  field_metadata:{indexValue:{validation_status:'INDICATIVE',decimal:'31.1034768'}}};
const silverDisplay=vm.runInContext('commodityDisplay(silver,inr)',ctx);
assert.equal(silverDisplay.quantity,'1 KG');
assert.equal(silverDisplay.rate,'≈ ₹94,490.00');
assert(silverDisplay.title.includes('1,000 grams'));
assert.equal(vm.runInContext('commodityDisplay({...silver,indexValue:null},inr).rate',ctx),'DATA UNAVAILABLE');
const commodityHtml=vm.runInContext("renderStocksTable([gold], 'commodities', inr)",ctx);
assert(commodityHtml.includes('<th>Reference</th>'));
assert(html.includes('<th>Reference</th>'));
assert(!html.includes('<th>Symbol</th>'));
ctx.referenceRow={...ctx.gold,changePercent:1,field_metadata:{
  indexValue:{validation_status:'INDICATIVE',decimal:'1',source:'Google Finance'},
  changePercent:{validation_status:'VERIFIED',decimal:'1',source:'Yahoo Finance'}}};
assert.equal(vm.runInContext("marketReference(referenceRow,'indexValue')",ctx),'Google Finance / Yahoo Finance');
assert.equal(vm.runInContext("marketReference({},'marketCap')",ctx),'No available source');
assert(commodityHtml.includes('Market Rate (INR)'));
assert(!commodityHtml.includes('Google series:'));
ctx.corn={...ctx.gold,ticker:'ZC=F',unit:'US¢/bushel',indexValue:500,
  field_metadata:{indexValue:{validation_status:'INDICATIVE',decimal:'500'}}};
assert.equal(vm.runInContext('commodityDisplay(corn,inr).rate',ctx),'≈ ₹472.45');
assert(vm.runInContext('commodityDisplay(corn,inr).note',ctx).includes('FX stale'));
assert.equal(vm.runInContext('commodityDisplay(corn).rate',ctx),'DATA UNAVAILABLE');
ctx.wrongFx={...ctx.inr,base_currency:'INR',quote_currency:'USD'};
assert.equal(vm.runInContext('commodityDisplay(corn,wrongFx).rate',ctx),'DATA UNAVAILABLE');
assert.equal((commodityHtml.match(/<th>/g)||[]).length,6);
assert(commodityHtml.includes('<th>Quantity</th>'));
assert.equal((html.match(/<th>/g)||[]).length,5);
ctx.gold.indexValue=null;
assert.equal(vm.runInContext('commodityDisplay(gold).rate',ctx),'DATA UNAVAILABLE');
assert.equal(vm.runInContext("commodityDisplay({unit:'USD/bbl'}).quantity",ctx),'1 Barrel');
assert.equal(vm.runInContext("commodityDisplay({unit:'USD/metric ton'}).quantity",ctx),'1 Ton');
assert(src.includes('verification_status'));
assert(fs.readFileSync('script.js','utf8').includes('setInterval(refreshData, 60000)'));
console.log('Frontend precision, missing data, row retention, safe URLs and refresh checks passed.');
ctx.AbortSignal = AbortSignal;
(async () => {
  ctx.fetch = async () => ({ ok: true, json: async () => ({ regions: {} }) });
  await assert.rejects(ctx.loadJSON('data/stocks.json'), /Invalid market snapshot/);
  ctx.fetch = async () => ({ ok: true, json: async () => ({ items: [null] }) });
  await assert.rejects(ctx.loadJSON('data/news_tech.json'), /Invalid news snapshot/);
  ctx.fetch = async () => ({ ok: false });
  await assert.rejects(ctx.loadJSON('data/stocks.json'), /Failed/);
  ctx.window.location.hostname = 'veda575.github.io';
  const requested = [];
  ctx.fetch = async url => {
    requested.push(url);
    if (url.startsWith('https://raw.githubusercontent.com/')) throw new Error('Network unavailable');
    return {ok:true, json:async()=>({items:[],updated:'2026-09-18T00:00:00Z'})};
  };
  const saved = await ctx.loadJSON('data/news_tech.json');
  assert.equal(saved.updated, '2026-09-18T00:00:00Z');
  assert.equal(requested.length, 2);
  assert(requested[1].startsWith('data/news_tech.json?'));
  console.log('Malformed market/news responses and HTTP failure checks passed.');
})().catch(e => { console.error(e); process.exitCode = 1; });

// Production data bypasses Pages publication delay.
ctx.window = {location: {hostname: 'veda575.github.io'}};
assert.equal(ctx.dataURL('data/stocks.json'), 'https://raw.githubusercontent.com/veda575/daily-brief/main/data/stocks.json');
ctx.window.location.hostname = 'localhost';
assert.equal(ctx.dataURL('data/stocks.json'), 'data/stocks.json');
// Stale commodities and indicative market caps must be visible without hovering.
ctx.staleCommodity = {...ctx.gold, validation_status:'STALE', source_timestamp:'2026-09-17T00:00:00Z'};
assert(vm.runInContext("renderStocksTable([staleCommodity], 'commodities', inr)",ctx).includes('<small>STALE'));
assert(vm.runInContext("renderStocksTable([fieldRow], 'us')",ctx).includes('INDICATIVE'));
