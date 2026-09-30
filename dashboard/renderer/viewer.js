const image=document.getElementById('image'),counter=document.getElementById('counter');
function render(item){if(!item)return;image.src=item.url;counter.textContent=`${item.index+1} / ${item.count}`;}
document.getElementById('previous').addEventListener('click',()=>window.roadRescue.viewerNavigate(-1));
document.getElementById('next').addEventListener('click',()=>window.roadRescue.viewerNavigate(1));
document.getElementById('close').addEventListener('click',()=>window.roadRescue.closeViewer());
document.addEventListener('keydown',(event)=>{if(event.key==='ArrowLeft')window.roadRescue.viewerNavigate(-1);if(event.key==='ArrowRight')window.roadRescue.viewerNavigate(1);if(event.key==='Escape')window.roadRescue.closeViewer();});
window.roadRescue.onViewerUpdated(render);window.roadRescue.viewerCurrent().then(render);
