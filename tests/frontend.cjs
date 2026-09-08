const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
// Exercise real rendering functions without starting the DOM initialization.
let src = fs.readFileSync('script.js', 'utf8').split('// ── Sidebar / hamburger / routing')[0];
const ctx = vm.createContext({ Intl, Date, Number, URL, Set });
vm.runInContext(src, ctx);
assert.equal(vm.runInContext("formatDecimal('123.0000')", ctx), '123.0000');
assert.equal(vm.runInContext("formatDecimal('123456.123456789')", ctx), '123,456.123456789');
assert.equal(vm.runInContext('fmtGainLossPercent(null)', ctx), 'DATA UNAVAILABLE');
assert.equal(vm.runInContext("safeNewsUrl('javascript:alert(1)')", ctx), '#');
assert.equal(vm.runInContext("fmtGainLossPercent(0, '0.0000')", ctx), '0.0000%');
const html = vm.runInContext("renderStocksTable([{name:'Legacy',ticker:'X',marketCap:123,indexValue:1,changePercent:null}], 'us')", ctx);
assert(html.includes('Legacy'));
assert(html.includes('DATA UNAVAILABLE'));
assert(!html.includes('0.00%'));
assert(src.includes('verification_status'));
assert(fs.readFileSync('script.js','utf8').includes('setInterval(refreshData, 300000)'));
console.log('Frontend precision, missing data, row retention, safe URLs and refresh checks passed.');
ctx.AbortSignal = AbortSignal;
(async () => {
  ctx.fetch = async () => ({ ok: true, json: async () => ({ regions: {} }) });
  await assert.rejects(ctx.loadJSON('data/stocks.json'), /Invalid market snapshot/);
  ctx.fetch = async () => ({ ok: true, json: async () => ({ items: [null] }) });
  await assert.rejects(ctx.loadJSON('data/news_tech.json'), /Invalid news snapshot/);
  ctx.fetch = async () => ({ ok: false });
  await assert.rejects(ctx.loadJSON('data/stocks.json'), /Failed/);
  console.log('Malformed market/news responses and HTTP failure checks passed.');
})().catch(e => { console.error(e); process.exitCode = 1; });
