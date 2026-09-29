const profileScript=document.createElement('script');
profileScript.src='/static/landing/js/profile-menu.js';
document.body.appendChild(profileScript);

const desktopStyles=document.createElement('link');
desktopStyles.rel='stylesheet';
desktopStyles.href='/static/landing/css/desktop-setup.css';
document.head.appendChild(desktopStyles);

const copyText=async(button,text,label='Copied ✓')=>{
 try{
  await navigator.clipboard.writeText(text.trim());
  const original=button.textContent;
  button.textContent=label;
  setTimeout(()=>button.textContent=original,1800);
 }catch{
  button.textContent='Select and copy';
 }
};

document.querySelectorAll('[data-copy-value]').forEach(button=>button.addEventListener('click',()=>{
 const target=button.dataset.copyValue==='token'?document.querySelector('[data-token-value]'):document.querySelector('[data-clone-value]');
 copyText(button,target?.textContent||'');
}));

document.querySelectorAll('[data-copy-command]').forEach(button=>button.addEventListener('click',()=>copyText(button,document.querySelector(`[data-command="${button.dataset.copyCommand}"]`)?.textContent||'')));
document.querySelectorAll('[data-launch-path]').forEach(button=>button.addEventListener('click',()=>{
 document.querySelectorAll('[data-launch-path]').forEach(item=>item.classList.toggle('active',item===button));
 document.querySelectorAll('[data-launch-panel]').forEach(panel=>panel.hidden=panel.dataset.launchPanel!==button.dataset.launchPath);
}));

const fileSearch=document.querySelector('[data-file-search]');
document.querySelector('[data-file-search-toggle]')?.addEventListener('click',()=>{
 fileSearch.hidden=!fileSearch.hidden;
 if(!fileSearch.hidden)fileSearch.querySelector('input').focus();
});
document.querySelector('[data-file-query]')?.addEventListener('input',event=>{
 const query=event.target.value.trim().toLowerCase();
 document.querySelectorAll('[data-file-name]').forEach(row=>row.hidden=query&&!row.dataset.fileName.includes(query));
});

const addFile=document.querySelector('[data-add-file]');
document.querySelector('[data-add-file-toggle]')?.addEventListener('click',()=>{
 addFile.hidden=false;
 addFile.scrollIntoView({behavior:'smooth'});
 addFile.querySelector('input[name="path"]').focus();
});
document.querySelector('[data-add-file-close]')?.addEventListener('click',()=>addFile.hidden=true);

const setupBody=document.querySelector('[data-setup-body]');
document.querySelector('[data-setup-toggle]')?.addEventListener('click',event=>{
 setupBody.hidden=!setupBody.hidden;
 event.currentTarget.setAttribute('aria-expanded',String(!setupBody.hidden));
 event.currentTarget.textContent=setupBody.hidden?'View setup guide ↓':'Hide setup guide ↑';
});
document.querySelectorAll('[data-os]').forEach(button=>button.addEventListener('click',()=>{
 document.querySelectorAll('[data-os]').forEach(item=>item.classList.toggle('active',item===button));
 document.querySelectorAll('[data-os-panel]').forEach(panel=>panel.hidden=panel.dataset.osPanel!==button.dataset.os);
}));
document.querySelector('[data-copy-install]')?.addEventListener('click',event=>copyText(event.currentTarget,'git --version'));
