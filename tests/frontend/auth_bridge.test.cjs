const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('frontend/auth_bridge/index.html', 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
function setup() {
  const calls=[], sent=[];
  const parent={postMessage:(data,origin)=>sent.push({data,origin}),location:{reload:()=>{}}};
  let handler;
  const context={URL,document:{referrer:'https://demo.example/chat'},
    window:{location:{origin:'https://demo.example'},parent,addEventListener:(type,fn)=>{handler=fn;}},
    fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({})};},setTimeout:fn=>fn()};
  vm.runInNewContext(script,context);
  return {calls,sent,parent,render:(args,extra={})=>handler({source:parent,origin:'https://demo.example',data:{type:'streamlit:render',args},...extra})};
}
const login={nonce:'n1',action:'login',api_url:'https://api.example',credentials:{username:'demo',password:'synthetic-password'}};
test('trusted login supports a separate HTTPS API and exact parent targets',async()=>{
 const app=setup();await app.render(login);assert.equal(app.calls[0].url,'https://api.example/auth/login');
 assert.equal(app.calls[0].options.credentials,'include');assert.ok(app.sent.every(x=>x.origin==='https://demo.example'));
 await app.render(login);assert.equal(app.calls.length,1);
});
test('spoofed source and origin never send credentials',async()=>{
 const app=setup();await app.render(login,{source:{}});await app.render(login,{origin:'https://evil.example'});assert.equal(app.calls.length,0);
});
test('untrusted actions and API destinations never cause a request',async()=>{
 for(const args of [{...login,action:'delete'},{...login,api_url:'http://remote.example'},
   {...login,api_url:'javascript:alert(1)'},{...login,api_url:'https://user:password@api.example'},
   {...login,credentials:null}]) {const app=setup();await app.render(args);assert.equal(app.calls.length,0);}
});
test('local development and logout remain supported',async()=>{
 const app=setup();await app.render({...login,api_url:'http://localhost:8000'});assert.equal(app.calls.length,1);
 await app.render({nonce:'n2',action:'logout',api_url:'http://localhost:8000'});assert.equal(app.calls[1].options.body,undefined);
});
test('malformed parent messages are ignored',async()=>{
 const app=setup();await app.render(null);await app.render({});await app.render(login,{data:null});assert.equal(app.calls.length,0);
});
