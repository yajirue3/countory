<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>村岡王国 - 国立機械工場</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <style>
        :root {
            --bg-body: #050505; --panel-bg: #121418; --panel-border: #2a313b;
            --accent-blue: #3b82f6; --accent-orange: #f59e0b; --accent-red: #ef4444;
            --text-main: #e2e8f0; --text-dim: #94a3b8;
        }

        body { 
            background: var(--bg-body); color: var(--text-main); 
            font-family: 'Consolas', monospace; margin: 0; padding: 10px; 
            display: flex; justify-content: center; min-height: 100vh; overflow-x: hidden;
        }

        .app-grid { display: grid; grid-template-columns: 1.3fr 1fr; gap: 15px; width: 100%; max-width: 1200px; }

        @media (max-width: 900px) {
            .app-grid { grid-template-columns: 1fr; }
            .viewport-section { height: 40vh; min-height: 280px; }
        }

        .viewport-section {
            background: #000; border: 2px solid var(--panel-border); border-radius: 8px;
            position: relative; box-shadow: 0 10px 30px rgba(0,0,0,0.9);
            overflow: hidden; display: flex; flex-direction: column;
        }
        #viewport-3d { width: 100%; height: 100%; flex: 1; }

        .cctv-osd {
            position: absolute; top: 12px; left: 12px; right: 12px; pointer-events: none;
            color: #fff; font-size: 0.85rem; text-shadow: 1px 1px 0 #000, -1px -1px 0 #000;
            display: flex; justify-content: space-between; z-index: 10; font-weight: bold;
        }
        .red-dot {
            display: inline-block; width: 10px; height: 10px; background: #ff003c; border-radius: 50%;
            animation: blink 1s infinite; margin-right: 6px; box-shadow: 0 0 8px #ff003c;
        }
        @keyframes blink { 50% { opacity: 0.3; } }

        .control-section {
            background: var(--panel-bg); border: 2px solid var(--panel-border);
            border-radius: 8px; padding: 15px; display: flex; flex-direction: column;
        }
        .header-panel {
            border-bottom: 1px dashed var(--panel-border); padding-bottom: 12px; margin-bottom: 12px;
            display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 10px;
        }
        .header-panel h2 { margin: 0; font-size: 1.15rem; color: var(--accent-blue); width: 100%; }

        select { 
            background: #0b0d10; color: var(--accent-blue); border: 1px solid var(--panel-border); 
            padding: 8px; font-family: inherit; border-radius: 4px; width: 100%;
        }

        .wear-container { font-size: 0.85rem; color: var(--accent-orange); display: flex; align-items: center; gap: 8px; width: 100%; font-weight:bold;}
        .wear-bar-bg { flex: 1; height: 10px; background: #0b0d10; border: 1px solid #333; border-radius: 2px;}
        .wear-bar-fill { height: 100%; background: var(--accent-orange); width: 0%; transition: width 0.4s ease; }

        .track-container { 
            background: #0b0d10; height: 14px; border: 1px solid var(--panel-border);
            margin: 10px 0 15px 0; display: flex; padding: 2px; gap: 2px; border-radius: 3px;
        }
        .track-node { flex: 1; background: #222; transition: all 0.3s; border-radius: 2px;}
        .track-node.active { background: var(--accent-blue); box-shadow: 0 0 8px var(--accent-blue); }
        .track-node.completed { background: #334155; }

        .action-area { 
            flex: 1; background: #0a0b0e; padding: 15px; border: 1px solid #1e293b; 
            border-radius: 6px; display: flex; flex-direction: column; gap: 12px;
        }
        .panel-title { font-size: 1rem; color: var(--accent-blue); border-left: 3px solid var(--accent-blue); padding-left: 8px; margin: 0; font-weight:bold;}
        .instruction-box { background: #151a22; padding: 12px; font-size: 0.85rem; line-height: 1.5; border-radius: 4px; border-left: 3px solid var(--accent-orange);}
        
        .btn-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .btn-machinery { 
            background: #1e293b; color: #f8fafc; border: 1px solid #334155; border-bottom: 4px solid #0f172a;
            padding: 12px; font-weight: bold; font-family: inherit; cursor: pointer; 
            border-radius: 4px; transition: transform 0.1s; font-size: 0.85rem; min-height: 48px;
        }
        .btn-machinery:active { transform: translateY(3px); border-bottom-width: 1px; }
        .btn-machinery:disabled { opacity: 0.5; cursor: not-allowed; }
        
        .btn-action { background: #1d4ed8; border-color: #3b82f6; grid-column: span 2; }
        .btn-maint { background: #991b1b; border-color: #f87171; grid-column: span 2; display: none; margin-bottom: 10px;}

        /* カラーコードのスイッチ盤 UI */
        .color-board { display: flex; flex-direction: column; gap: 8px; }
        .color-row { display: flex; align-items: center; gap: 8px; }
        .color-label { width: 50px; font-size: 0.75rem; color: var(--text-dim); text-align: right; }
        .color-swatches { display: flex; flex: 1; gap: 4px; overflow-x: auto; padding-bottom: 4px; }
        .swatch { 
            min-width: 40px; height: 32px; border: 2px solid #333; border-radius: 4px; 
            cursor: pointer; display: flex; justify-content: center; align-items: center;
            font-size: 0.75rem; font-weight: bold; color: #fff; text-shadow: 1px 1px 0 #000;
        }
        .swatch.selected { border-color: #fff; box-shadow: 0 0 8px rgba(255,255,255,0.5); transform: scale(1.05); }

        .gauge-container { width: 100%; background: #000; height: 28px; border: 1px solid var(--panel-border); position: relative; overflow: hidden; border-radius:4px;}
        .gauge-target { position: absolute; left: 45%; width: 10%; height: 100%; background: rgba(59, 130, 246, 0.2); border-left: 2px solid var(--accent-blue); border-right: 2px solid var(--accent-blue); }
        .gauge-pointer { position: absolute; width: 4px; height: 100%; background: var(--accent-red); left: 0%; box-shadow: 0 0 6px var(--accent-red); }

        .console-log { 
            background: #050608; border: 1px solid #1e293b; padding: 12px; height: 100px; 
            overflow-y: auto; font-size: 0.8rem; color: #10b981; margin-top: 15px; border-radius: 4px; line-height: 1.4;
        }
        .btn-back { background: #1e293b; color: #cbd5e1; border: none; padding: 14px; margin-top: 10px; cursor: pointer; border-radius: 4px; width: 100%; font-weight:bold;}
        
        .loading-overlay {
            position: absolute; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.6);
            display: flex; justify-content: center; align-items: center; color: var(--accent-blue);
            z-index: 50; display: none; font-weight: bold; font-size: 1.2rem;
        }
    </style>
</head>
<body>

<div class="app-grid">
    <div class="viewport-section">
        <div class="cctv-osd">
            <div><span class="red-dot"></span>SYS_REC</div>
            <div id="cctv-cam">CAM-01 [RECEIVE]</div>
        </div>
        <div id="viewport-3d"></div>
        <div id="loadingOverlay" class="loading-overlay">TRANSMITTING...</div>
    </div>

    <div class="control-section">
        <div class="header-panel">
            <h2>FACTORY_MURAOKA_01</h2>
            <div class="wear-container">
                <span>WEAR:</span><div class="wear-bar-bg"><div class="wear-bar-fill" id="wearBar"></div></div><span id="wearText">0%</span>
            </div>
            <select id="walletSelect"><option value="">Loading accounts...</option></select>
        </div>

        <button id="btnMaint" class="btn-machinery btn-maint" onclick="performMaintenance()">⚠️ 設備摩耗限界 - 手動エアパージ</button>

        <div class="track-container">
            <div id="node1" class="track-node"></div><div id="node2" class="track-node"></div>
            <div id="node3" class="track-node"></div><div id="node4" class="track-node"></div>
            <div id="node5" class="track-node"></div>
        </div>

        <div class="action-area" id="actionArea"></div>

        <div class="console-log" id="consoleLog">> SYSTEM BOOT.<br></div>
        <button class="btn-back" onclick="location.href='/dashboard'">◀ ラインから退出</button>
    </div>
</div>

<script>
// --- 音響 (Web Audio API) ---
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
function playSound(type) {
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const osc = audioCtx.createOscillator(), gain = audioCtx.createGain();
    osc.connect(gain); gain.connect(audioCtx.destination);
    const now = audioCtx.currentTime;
    if (type === 'click') {
        osc.type = 'square'; osc.frequency.setValueAtTime(800, now); osc.frequency.exponentialRampToValueAtTime(300, now+0.05);
        gain.gain.setValueAtTime(0.05, now); gain.gain.exponentialRampToValueAtTime(0.01, now+0.05);
        osc.start(now); osc.stop(now+0.05);
    } else if (type === 'error') {
        osc.type = 'sawtooth'; osc.frequency.setValueAtTime(100, now);
        gain.gain.setValueAtTime(0.1, now); gain.gain.linearRampToValueAtTime(0, now+0.3);
        osc.start(now); osc.stop(now+0.3);
    } else if (type === 'heavy') { 
        osc.type = 'square'; osc.frequency.setValueAtTime(120, now); osc.frequency.exponentialRampToValueAtTime(20, now+0.25);
        gain.gain.setValueAtTime(0.2, now); gain.gain.exponentialRampToValueAtTime(0.01, now+0.25);
        osc.start(now); osc.stop(now+0.25);
    }
}

// --- 質感生成 (プロシージャル・バンプマップ) ---
// 外部画像を読まずに、Canvas経由で「鉄のザラザラ感」を作る
function createNoiseTexture() {
    const cvs = document.createElement('canvas'); cvs.width = 256; cvs.height = 256;
    const ctx = cvs.getContext('2d');
    const imgData = ctx.createImageData(256, 256);
    for (let i = 0; i < imgData.data.length; i += 4) {
        const v = Math.random() * 255;
        imgData.data[i] = v; imgData.data[i+1] = v; imgData.data[i+2] = v; imgData.data[i+3] = 255;
    }
    ctx.putImageData(imgData, 0, 0);
    const tex = new THREE.CanvasTexture(cvs);
    tex.wrapS = THREE.RepeatWrapping; tex.wrapT = THREE.RepeatWrapping;
    return tex;
}

// --- Three.js 究極の作り込み & 軽量化 ---
const vp = document.getElementById('viewport-3d');
const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x050608, 0.05);
const camera = new THREE.PerspectiveCamera(40, vp.clientWidth / vp.clientHeight, 0.1, 100);
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setSize(vp.clientWidth, vp.clientHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
vp.appendChild(renderer.domElement);

window.addEventListener('resize', () => {
    camera.aspect = vp.clientWidth / vp.clientHeight; camera.updateProjectionMatrix();
    renderer.setSize(vp.clientWidth, vp.clientHeight);
});

// ライティング
const ambientLight = new THREE.AmbientLight(0xffffff, 0.6); scene.add(ambientLight);
const dirLight = new THREE.DirectionalLight(0xffeedd, 1.5); 
dirLight.position.set(5, 10, 5); dirLight.castShadow = true; 
dirLight.shadow.mapSize.width = 512; dirLight.shadow.mapSize.height = 512;
scene.add(dirLight);
const bluePoint = new THREE.PointLight(0x3b82f6, 1.5, 10); bluePoint.position.set(-3, 3, 2); scene.add(bluePoint);

// マテリアル定義 (バンプマップ適用でデコボコ感を出す)
const noiseTex = createNoiseTexture();
const matIron = new THREE.MeshStandardMaterial({ color: 0x222428, roughness: 0.8, metalness: 0.6, bumpMap: noiseTex, bumpScale: 0.03 });
const matSteel = new THREE.MeshStandardMaterial({ color: 0x777c85, roughness: 0.4, metalness: 0.8, bumpMap: noiseTex, bumpScale: 0.01 });
const matBrass = new THREE.MeshStandardMaterial({ color: 0xa6903f, roughness: 0.3, metalness: 0.9 });
const matOrange = new THREE.MeshStandardMaterial({ color: 0xd97706, roughness: 0.6, metalness: 0.2 });

// 背景 (床と鉄骨)
const floor = new THREE.Mesh(new THREE.PlaneGeometry(30, 30), matIron);
floor.rotation.x = -Math.PI/2; floor.position.y = -2; floor.receiveShadow = true; scene.add(floor);
for(let i=0; i<3; i++){
    const col = new THREE.Mesh(new THREE.BoxGeometry(0.5, 20, 0.5), matIron);
    col.position.set(-6 + (i*6), 0, -4); col.castShadow = true; col.receiveShadow = true; scene.add(col);
}

// 全工程のモデルを事前生成してキャッシュ
const steps3D = {};

// 1. ベアリング (TorusとSphereで精巧に)
steps3D[1] = new THREE.Group();
const bOuter = new THREE.Mesh(new THREE.TorusGeometry(1.0, 0.2, 16, 32), matSteel);
const bInner = new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.15, 16, 32), matSteel);
steps3D[1].add(bOuter, bInner);
for(let i=0; i<8; i++){
    const ball = new THREE.Mesh(new THREE.SphereGeometry(0.2, 16, 16), matSteel);
    ball.position.set(Math.cos(i/8*Math.PI*2)*0.75, Math.sin(i/8*Math.PI*2)*0.75, 0);
    steps3D[1].add(ball);
}
steps3D[1].rotation.x = Math.PI/2; steps3D[1].position.y = 0;
steps3D[1].traverse(c => { if(c.isMesh){ c.castShadow=true; c.receiveShadow=true; } });

// 2. 抵抗器 (キャップとワイヤーを別々に)
steps3D[2] = new THREE.Group();
const rBody = new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.4, 1.8, 32), new THREE.MeshStandardMaterial({color:0xd9c5a0, roughness:1.0}));
rBody.rotation.z = Math.PI/2; steps3D[2].add(rBody);
const wireGeo = new THREE.CylinderGeometry(0.05, 0.05, 1.5, 16);
const w1 = new THREE.Mesh(wireGeo, matSteel); w1.rotation.z = Math.PI/2; w1.position.x = 1.6;
const w2 = new THREE.Mesh(wireGeo, matSteel); w2.rotation.z = Math.PI/2; w2.position.x = -1.6;
steps3D[2].add(w1, w2);
const bands = [];
for(let i=0; i<4; i++){
    const b = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.42, 0.15, 32), new THREE.MeshBasicMaterial({color:0x000}));
    b.rotation.z = Math.PI/2; b.position.x = -0.6 + (i*0.4); steps3D[2].add(b); bands.push(b);
}
steps3D[2].position.y = 1;
steps3D[2].traverse(c => { if(c.isMesh){ c.castShadow=true; c.receiveShadow=true; } });

// 3. クラッチ (歯車形状をExtrudeGeometryで正確に生成)
function createGearMesh() {
    const shape = new THREE.Shape();
    const teeth = 16, rOut = 1.2, rIn = 0.9;
    for(let i=0; i<teeth*2; i++) {
        const a = (i/(teeth*2))*Math.PI*2, r = i%2===0 ? rOut : rIn;
        if(i===0) shape.moveTo(Math.cos(a)*r, Math.sin(a)*r); else shape.lineTo(Math.cos(a)*r, Math.sin(a)*r);
    }
    const geo = new THREE.ExtrudeGeometry(shape, { depth: 0.3, bevelEnabled: true, bevelSegments: 2, bevelSize: 0.05, bevelThickness: 0.05 });
    return new THREE.Mesh(geo, matBrass);
}
steps3D[3] = new THREE.Group();
const gear1 = createGearMesh(); gear1.position.z = -0.2; gear1.rotation.x = Math.PI/2;
const gear2 = createGearMesh(); gear2.position.z = 0.3; gear2.rotation.x = Math.PI/2;
steps3D[3].add(gear1, gear2);
steps3D[3].position.y = 1;
steps3D[3].traverse(c => { if(c.isMesh){ c.castShadow=true; c.receiveShadow=true; } });

// 4. 油圧シリンダー (リブ付きの重厚なシリンダー)
steps3D[4] = new THREE.Group();
const cylGroup = new THREE.Group();
const mainCyl = new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.8, 2, 32), matIron); cylGroup.add(mainCyl);
for(let i=0; i<4; i++){
    const rib = new THREE.Mesh(new THREE.TorusGeometry(0.82, 0.1, 16, 32), matIron);
    rib.position.y = -0.6 + (i*0.4); cylGroup.rotation.x = Math.PI/2; cylGroup.add(rib);
}
cylGroup.position.set(0, 0, 0); steps3D[4].add(cylGroup);
const rod = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.3, 2.5, 32), matSteel); rod.position.y = 1.5; steps3D[4].add(rod);
steps3D[4].position.y = 0;
steps3D[4].traverse(c => { if(c.isMesh){ c.castShadow=true; c.receiveShadow=true; } });

// 5. 巨大プレス機
steps3D[5] = new THREE.Group();
const pressBase = new THREE.Mesh(new THREE.BoxGeometry(3, 0.5, 2), matIron);
const pressHead = new THREE.Mesh(new THREE.BoxGeometry(2, 1.5, 1.5), matOrange); pressHead.position.y = 2.5;
steps3D[5].add(pressBase, pressHead);
steps3D[5].position.y = 0;
steps3D[5].traverse(c => { if(c.isMesh){ c.castShadow=true; c.receiveShadow=true; } });

// シーンに全て追加し、非表示
for(let i=1; i<=5; i++) { steps3D[i].visible = false; scene.add(steps3D[i]); }

// カメラLerp制御 (映画的な動き)
const camTargetPos = new THREE.Vector3(0, 5, 8);
const camTargetLook = new THREE.Vector3(0, 0, 0);
const currentLook = new THREE.Vector3(0, 0, 0);

const camViews = {
    1: { pos: [-3, 4, 5], look: [0, 0, 0], text: "CAM-01 [RECEIVE]" },
    2: { pos: [0, 3.5, 4], look: [0, 1, 0], text: "CAM-02 [CALIBRATE]" },
    3: { pos: [2.5, 3, 5], look: [0, 1, 0], text: "CAM-03 [CLUTCH]" },
    4: { pos: [1.5, 2.5, 5], look: [0, 1, 0], text: "CAM-04 [PRESSURE]" },
    5: { pos: [3.5, 3.5, 5.5], look: [0, 1, 0], text: "CAM-05 [PRESS_OUT]" }
};

function switchStep3D(step) {
    for(let i=1; i<=5; i++) steps3D[i].visible = (i === step);
    const v = camViews[step] || camViews[1];
    camTargetPos.set(...v.pos); camTargetLook.set(...v.look);
    document.getElementById('cctv-cam').innerText = v.text;
}

function animate() {
    requestAnimationFrame(animate);
    camera.position.lerp(camTargetPos, 0.06);
    currentLook.lerp(camTargetLook, 0.06);
    camera.lookAt(currentLook);

    if(steps3D[1].visible) { steps3D[1].rotation.y += 0.01; }
    if(steps3D[3].visible && !isLocked) { gear1.rotation.z += 0.04; gear2.rotation.z -= 0.02; }
    if(steps3D[4].visible && rod.position.y < 1.5) { rod.position.y += (1.5 - rod.position.y) * 0.1; } // ピストンの戻り

    renderer.render(scene, camera);
}
animate();

// --- ロジック & UI ---
const token = localStorage.getItem("access_token") || localStorage.getItem("token");
if (!token) window.location.href = "/";

let currentSession = null, gaugeVal = 0, gaugeDir = 2, gaugeInterval = null, tapCount = 0;
let isLocked = false, isFetching = false;
let selectedColors = [0, 0, 0, 10]; // 初期値: 黒,黒,黒,金

const cData = {
    bands: [
        {v:0, n:"黒(0)", c:"#222", t:"#fff"}, {v:1, n:"茶(1)", c:"#8b4513", t:"#fff"}, {v:2, n:"赤(2)", c:"#ef4444", t:"#fff"}, {v:3, n:"橙(3)", c:"#f97316", t:"#000"},
        {v:4, n:"黄(4)", c:"#eab308", t:"#000"}, {v:5, n:"緑(5)", c:"#22c55e", t:"#000"}, {v:6, n:"青(6)", c:"#3b82f6", t:"#fff"}, {v:7, n:"紫(7)", c:"#a855f7", t:"#fff"},
        {v:8, n:"灰(8)", c:"#64748b", t:"#fff"}, {v:9, n:"白(9)", c:"#ffffff", t:"#000"}
    ],
    mults: [
        {v:0, n:"x10^0", c:"#222", t:"#fff"}, {v:1, n:"x10^1", c:"#8b4513", t:"#fff"}, {v:2, n:"x10^2", c:"#ef4444", t:"#fff"},
        {v:3, n:"x10^3", c:"#f97316", t:"#000"}, {v:4, n:"x10^4", c:"#eab308", t:"#000"}
    ],
    tols: [
        {v:10, n:"金(±5%)", c:"#d4af37", t:"#000"}, {v:11, n:"銀(±10%)", c:"#c0c0c0", t:"#000"}
    ]
};

async function initFactory() {
    try {
        const res = await fetch('/api/wallets', { headers: { 'Authorization': `Bearer ${token}` } });
        if(res.ok) {
            const w = await res.json();
            document.getElementById('walletSelect').innerHTML = w.length===0 ? '<option value="">口座なし</option>' : w.map(x=>`<option value="${x.wallet_id}">${x.wallet_name} - ${Math.floor(x.balance)}G</option>`).join('');
        }
    } catch(e) {}
    await fetchStatus();
}

function logMessage(msg) {
    const log = document.getElementById('consoleLog');
    log.innerHTML += `> ${msg}<br>`; log.scrollTop = log.scrollHeight;
}

// 汎用エラーキャッチ (バックエンドから返された詳細理由を表示する)
async function fetchStatus() {
    try {
        const res = await fetch('/api/factory/status', { headers: { 'Authorization': `Bearer ${token}` } });
        if(!res.ok) {
            let errStr = "サーバー応答エラー";
            try { const errObj = await res.json(); errStr = errObj.detail || errStr; } catch(e){}
            logMessage(`<span style='color:var(--accent-red);'>[ERROR] ${errStr}</span>`);
            return;
        }
        const data = await res.json();
        currentSession = data.session;
        updateWear(data.wear); renderStep();
    } catch(e) { logMessage(`<span style='color:var(--accent-red);'>[ERROR] 通信に失敗しました。(${e.message})</span>`); }
}

function updateWear(wear) {
    document.getElementById('wearBar').style.width = `${wear}%`;
    document.getElementById('wearText').innerText = `${wear}%`;
    isLocked = (wear >= 100);
    document.getElementById('btnMaint').style.display = isLocked ? 'block' : 'none';
}

async function performMaintenance() {
    if(isFetching) return; isFetching = true;
    try {
        const res = await fetch('/api/factory/maintain', { method: 'POST', headers: { 'Authorization': `Bearer ${token}` } });
        const data = await res.json();
        logMessage(`<span style="color:var(--accent-blue);">${data.message}</span>`);
        updateWear(data.wear);
    } catch(e) {} finally { isFetching = false; }
}

function renderStep() {
    if(!currentSession) return;
    const step = currentSession.current_step;
    document.getElementById('stepTitle').innerText = currentSession.title;
    switchStep3D(step);
    
    for (let i = 1; i <= 5; i++) {
        const n = document.getElementById(`node${i}`);
        n.className = 'track-node' + (i < step ? ' completed' : (i === step ? ' active' : ''));
    }

    const area = document.getElementById('actionArea');
    
    if (step === 1) {
        area.innerHTML = `<div class="instruction-box">要求仕様: <b style="color:var(--accent-orange);">${currentSession.target_part}</b></div>
            <div class="btn-grid">${currentSession.options.map(opt => `<button class="btn-machinery" onclick="submitStep(${step}, '${opt}')">${opt}</button>`).join('')}</div>`;
    } else if (step === 2) {
        area.innerHTML = `<div class="instruction-box">${currentSession.math_question}</div>
            <div class="color-board">
                ${buildColorRow(0, "第1帯", cData.bands)}
                ${buildColorRow(1, "第2帯", cData.bands)}
                ${buildColorRow(2, "乗数", cData.mults)}
                ${buildColorRow(3, "公差", cData.tols)}
            </div><button class="btn-machinery btn-action" onclick="submitStep(2, selectedColors)">カラーバンド書込</button>`;
        applyColorTo3D();
    } else if (step === 3) {
        area.innerHTML = `<div class="instruction-box">${currentSession.instruction}</div>
            <div class="gauge-container"><div class="gauge-target"></div><div id="pointer" class="gauge-pointer"></div></div>
            <button class="btn-machinery btn-action" onclick="stopGauge(${step})">クラッチ結合 [LOCK]</button>`;
        startGauge();
    } else if (step === 4) {
        tapCount = 0;
        area.innerHTML = `<div class="instruction-box">${currentSession.instruction}</div>
            <div style="font-size:1.4rem; font-weight:bold; color:var(--accent-blue); text-align:center; padding:10px;">圧力: <span id="taps">0</span> / 10 Bar</div>
            <button class="btn-machinery btn-action" onclick="countTap(${step})">加圧ストローク [PUMP]</button>`;
    } else if (step === 5) {
        area.innerHTML = `<div class="instruction-box">${currentSession.instruction}</div>
            <button class="btn-machinery btn-action" style="background:var(--accent-orange); border-color:#fff;" onclick="submitStep(${step}, true)">出荷打刻・口座転送</button>`;
    }
}

// カスタムカラーパレットのHTML生成
function buildColorRow(bandIdx, label, opts) {
    let html = `<div class="color-row"><div class="color-label">${label}</div><div class="color-swatches">`;
    opts.forEach(o => {
        const sel = selectedColors[bandIdx] === o.v ? ' selected' : '';
        html += `<div class="swatch${sel}" style="background:${o.c}; color:${o.t}" onclick="pickColor(${bandIdx}, ${o.v})">${o.n.split('(')[0]}</div>`;
    });
    html += `</div></div>`;
    return html;
}

window.pickColor = function(bandIdx, val) {
    selectedColors[bandIdx] = val;
    renderStep(); // UI再描画
    applyColorTo3D();
};

function applyColorTo3D() {
    for(let i=0; i<4; i++){
        let hex = "#000";
        if(i < 3) {
            const row = (i===2) ? cData.mults : cData.bands;
            hex = row.find(c=>c.v === selectedColors[i]).c;
        } else {
            hex = selectedColors[3] === 10 ? "#d4af37" : "#c0c0c0";
        }
        bands[i].material.color.set(hex);
    }
}

function startGauge() {
    gaugeVal = 0; gaugeDir = 2.5; clearInterval(gaugeInterval);
    gaugeInterval = setInterval(() => {
        gaugeVal += gaugeDir;
        if (gaugeVal >= 100 || gaugeVal <= 0) gaugeDir *= -1;
        const p = document.getElementById('pointer'); if(p) p.style.left = `${gaugeVal}%`;
    }, 20);
}
function stopGauge(step) { clearInterval(gaugeInterval); submitStep(step, Math.floor(gaugeVal)); }

function countTap(step) {
    if(isLocked || isFetching) return;
    tapCount++; playSound('heavy');
    rod.position.y = 0.8; // 押し込みアニメ (Lerpで戻る)
    document.getElementById('taps').innerText = tapCount;
    if (tapCount >= 10) setTimeout(() => submitStep(step, tapCount), 300);
}

async function submitStep(step, answer) {
    if (isLocked || isFetching) return;
    const walletId = document.getElementById('walletSelect').value;
    if (step === 5 && !walletId) { logMessage("<span style='color:var(--accent-red);'>ERROR: 出荷先口座を選択してください。</span>"); return; }

    isFetching = true;
    document.getElementById('loadingOverlay').style.display = 'flex';

    try {
        const res = await fetch('/api/factory/process', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ step: step, answer: answer, wallet_id: walletId })
        });
        
        if (!res.ok) {
            let errStr = "エラーが発生しました";
            try { const errObj = await res.json(); errStr = errObj.detail || errStr; } catch(e){}
            logMessage(`<span style="color:var(--accent-red);">${errStr}</span>`); playSound('error');
            if(errStr.includes("WEAR")) updateWear(100);
            else setTimeout(()=> fetchStatus(), 1500);
            return;
        }

        const data = await res.json();
        updateWear(data.wear); playSound('click');
        
        if (step === 5) { 
            playSound('heavy'); 
            pressHead.position.y = 0.5; setTimeout(()=>{pressHead.position.y = 2.5;}, 400); // プレスアニメ
        }

        if (data.completed) {
            logMessage(`<span style="color:var(--accent-blue);">${data.message}</span>`);
            // 口座残高更新
            fetch('/api/wallets', { headers: { 'Authorization': `Bearer ${token}` } }).then(r=>r.json()).then(w => {
                document.getElementById('walletSelect').innerHTML = w.map(x=>`<option value="${x.wallet_id}">${x.wallet_name} - ${Math.floor(x.balance)}G</option>`).join('');
            });
            selectedColors = [0, 0, 0, 10]; // カラーコードリセット
        }
        currentSession = data.next_step;
        setTimeout(() => renderStep(), 600); // アニメーションの余韻
    } catch(e) { 
        logMessage(`<span style='color:var(--accent-red);'>[ERROR] 通信に失敗しました。(${e.message})</span>`); 
    } finally {
        isFetching = false;
        document.getElementById('loadingOverlay').style.display = 'none';
    }
}

window.onload = initFactory;
</script>
</body>
</html>
