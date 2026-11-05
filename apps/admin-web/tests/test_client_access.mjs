import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {readBody,failureMessage} from '../public/api-response.mjs';
const source=(await readFile(new URL('../public/client-access.js',import.meta.url),'utf8')).replace(/^import .*;\n/,'');
const html=await readFile(new URL('../public/index.html',import.meta.url),'utf8');
function setup(){
  const ids=new Set([...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1])),nodes=new Map(),requests=[],hooks=[];
  function node(){return {value:'',textContent:'',hidden:false,disabled:false,children:[],dataset:{},className:'',classList:{toggle(){}},append(...kids){this.children.push(...kids);},replaceChildren(){this.children=[];},setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];},focus(){},select(){this.selected=true;}};}
  for(const id of ids)nodes.set(id,node());
  const copied=[];
  vm.runInNewContext(source,{document:{getElementById:id=>nodes.get(id)||null,createElement:node,createTextNode:text=>({textContent:text})},window:{addEventListener:(_type,fn)=>hooks.push(fn)},location:{href:'http://127.0.0.1:19765/#connections',hash:'#connections'},URL,navigator:{clipboard:{writeText:async text=>copied.push(text)}},readBody,failureMessage,
    fetch:async(path,options={})=>{
      requests.push({path,...options});
      if(options.method==='POST')return Response.json({token:'a-test-connection-secret',name:JSON.parse(options.body).name},{status:201});
      if(options.method==='DELETE')return Response.json({ok:true});
      return Response.json(path.includes('device-credentials')?{devices:[]}:{client_url:'http://127.0.0.1:19768/demo/',clients:[{id:'internal-secret-id',name:'我的网页'}]});
    }});
  return {nodes,requests,copied,async show(){for(const hook of hooks)await hook({detail:'connections'});}};
}
test('first-time guide uses a default name, copies code and opens the configured client URL',async()=>{
  const ui=setup();await ui.show();
  await ui.nodes.get('client-access-form').onsubmit({preventDefault(){}});
  const created=ui.requests.find(r=>r.method==='POST');
  assert.equal(JSON.parse(created.body).name,'这台电脑的网页');
  await ui.nodes.get('client-access-copy').onclick();
  assert.deepEqual(ui.copied,['a-test-connection-secret']);
  assert.equal(ui.nodes.get('client-access-open').href,'http://127.0.0.1:19768/demo/');
  assert.ok(!ui.nodes.get('client-access-open').href.includes('secret'));
  assert.equal(ui.nodes.get('client-access-secret').hidden,false);
});
test('allowed web entries show readable names and a plain-language disconnect action',async()=>{
  const ui=setup();await ui.show();
  const row=ui.nodes.get('client-access-list').children[0];
  assert.equal(row.children[0].textContent,'我的网页');
  assert.equal(row.children[1].textContent,'取消连接权限');
  await row.children[1].onclick();
  assert.ok(ui.requests.some(r=>r.method==='DELETE'&&r.path.endsWith('/internal-secret-id')));
});

test('opening connections directly loads the entry link without another menu click',async()=>{
  const ui=setup();await new Promise(setImmediate);
  assert.equal(ui.nodes.get('client-access-open').href,'http://127.0.0.1:19768/demo/');
});
