document.addEventListener('click',event=>{document.querySelectorAll('details.app-menu[open]').forEach(menu=>{if(!menu.contains(event.target))menu.removeAttribute('open')})});
document.addEventListener('keydown',event=>{if(event.key==='Escape')document.querySelectorAll('details.app-menu[open]').forEach(menu=>{menu.removeAttribute('open');menu.querySelector('summary')?.focus()})});
if(location.hash==='#new-project')document.querySelector('.project-dialog')?.showModal();
document.querySelectorAll('.tabs a.active').forEach(tab=>{const strip=tab.parentElement;if(strip.scrollWidth>strip.clientWidth)strip.scrollLeft=tab.offsetLeft-(strip.clientWidth-tab.offsetWidth)/2});
