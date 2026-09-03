/**
 * 数据迁移脚本：Supabase → Firestore
 * 
 * 使用方法：
 * 1. 在浏览器控制台先确保已连接 Supabase（默认模式）
 * 2. 粘贴此脚本到控制台运行
 * 3. 等待迁移完成
 * 4. 运行 switchDBProvider('firestore') 切换到 Firestore
 * 5. 刷新页面验证数据
 * 
 * 反向迁移（Firestore → Supabase）：
 * 先切换到 Firestore 模式，刷新页面，然后运行 migrateFirestoreToSupabase()
 */

// ====== Supabase → Firestore 迁移 ======
async function migrateSupabaseToFirestore() {
  if (!window.supabase) {
    console.error('Supabase SDK not loaded');
    return;
  }

  // 初始化 Supabase 客户端（读取源数据）
  const srcClient = window.supabase.createClient(
    'https://txtduqfhugjupxdoxdvp.supabase.co',
    'sb_publishable_EkzlCBH5DJu0OmFIUnGIZA_yiRPTvJA'
  );

  // 初始化 Firestore 客户端（写入目标）
  const FIREBASE_CONFIG = {
    apiKey: "AIzaSyDouEYiYfb2BUXKDYLB2cHwwfXpc6ddq50",
    authDomain: "clockin-b691a.firebaseapp.com",
    projectId: "clockin-b691a",
    storageBucket: "clockin-b691a.firebasestorage.app",
    messagingSenderId: "65997007825",
    appId: "1:65997007825:web:3712574e0225337d3e0ef0"
  };

  let fsApp, fsDb;
  try {
    fsApp = firebase.initializeApp(FIREBASE_CONFIG, 'migration');
    fsDb = firebase.firestore();
    console.log('Firestore connected');
  } catch(e) {
    console.error('Firestore init failed:', e);
    console.log('请先配置 FIREBASE_CONFIG');
    return;
  }

  console.log('🚀 开始迁移 Supabase → Firestore...\n');

  // 1. 迁移 config 表
  console.log('📦 迁移 config 表...');
  try {
    const { data: configRows, error } = await srcClient.from('config').select('*');
    if (error) throw error;
    
    const batch = fsDb.batch();
    (configRows || []).forEach(row => {
      const docRef = fsDb.collection('config').doc(row.id);
      const { id, ...data } = row;
      batch.set(docRef, data);
    });
    await batch.commit();
    console.log(`  ✅ config: ${configRows?.length || 0} 条记录`);
  } catch(e) {
    console.error('  ❌ config 迁移失败:', e);
  }

  // 2. 迁移 punches 表
  console.log('📦 迁移 punches 表...');
  try {
    const { data: punchRows, error } = await srcClient.from('punches').select('*');
    if (error) throw error;
    
    // Firestore 批量写入每次最多 500 条
    const chunks = [];
    for (let i = 0; i < (punchRows?.length || 0); i += 500) {
      chunks.push(punchRows.slice(i, i + 500));
    }
    
    let total = 0;
    for (const chunk of chunks) {
      const batch = fsDb.batch();
      chunk.forEach(row => {
        const docRef = row.id 
          ? fsDb.collection('punches').doc(String(row.id))
          : fsDb.collection('punches').doc();
        const { id, ...data } = row;
        batch.set(docRef, data);
      });
      await batch.commit();
      total += chunk.length;
    }
    console.log(`  ✅ punches: ${total} 条记录`);
  } catch(e) {
    console.error('  ❌ punches 迁移失败:', e);
  }

  // 3. 迁移 claims 表
  console.log('📦 迁移 claims 表...');
  try {
    const { data: claimRows, error } = await srcClient.from('claims').select('*');
    if (error) throw error;
    
    const batch = fsDb.batch();
    (claimRows || []).forEach(row => {
      const docRef = fsDb.collection('claims').doc(String(row.id));
      const { id, ...data } = row;
      batch.set(docRef, data);
    });
    await batch.commit();
    console.log(`  ✅ claims: ${claimRows?.length || 0} 条记录`);
  } catch(e) {
    console.error('  ❌ claims 迁移失败:', e);
  }

  // 4. 迁移 logs 表
  console.log('📦 迁移 logs 表...');
  try {
    const { data: logRows, error } = await srcClient.from('logs').select('*').order('ts', {ascending: false}).limit(1000);
    if (error) throw error;
    
    const batch = fsDb.batch();
    (logRows || []).forEach(row => {
      const docRef = fsDb.collection('logs').doc();
      batch.set(docRef, row);
    });
    await batch.commit();
    console.log(`  ✅ logs: ${logRows?.length || 0} 条记录（最近1000条）`);
  } catch(e) {
    console.error('  ❌ logs 迁移失败:', e);
  }

  // 5. 迁移 picks 表（如果有独立表）
  console.log('📦 检查 picks 表...');
  try {
    const { data: pickRows, error } = await srcClient.from('picks').select('*');
    if (!error && pickRows?.length > 0) {
      const batch = fsDb.batch();
      pickRows.forEach(row => {
        const docRef = fsDb.collection('picks').doc();
        batch.set(docRef, row);
      });
      await batch.commit();
      console.log(`  ✅ picks: ${pickRows.length} 条记录`);
    } else {
      console.log('  ℹ️  picks 表为空或不存在（选班数据已在 config.picks 中）');
    }
  } catch(e) {
    console.log('  ℹ️  picks 表不存在（正常，选班数据在 config.picks 中）');
  }

  console.log('\n✅ 迁移完成！');
  console.log('接下来运行: switchDBProvider("firestore") 然后刷新页面');
  
  // 清理
  try { fsApp.delete(); } catch(e) {}
}

// ====== Firestore → Supabase 反向迁移 ======
async function migrateFirestoreToSupabase() {
  // 初始化 Supabase
  const dstClient = window.supabase.createClient(
    'https://txtduqfhugjupxdoxdvp.supabase.co',
    'sb_publishable_EkzlCBH5DJu0OmFIUnGIZA_yiRPTvJA'
  );

  // 初始化 Firestore（读取源数据）
  const FIREBASE_CONFIG = {
    apiKey: "AIzaSyDouEYiYfb2BUXKDYLB2cHwwfXpc6ddq50",
    authDomain: "clockin-b691a.firebaseapp.com",
    projectId: "clockin-b691a",
    storageBucket: "clockin-b691a.firebasestorage.app",
    messagingSenderId: "65997007825",
    appId: "1:65997007825:web:3712574e0225337d3e0ef0"
  };

  let fsApp, fsDb;
  try {
    fsApp = firebase.initializeApp(FIREBASE_CONFIG, 'migration-reverse');
    fsDb = firebase.firestore();
  } catch(e) {
    console.error('Firestore init failed:', e);
    return;
  }

  console.log('🚀 开始反向迁移 Firestore → Supabase...\n');

  // 1. 迁移 config
  console.log('📦 迁移 config...');
  try {
    const snap = await fsDb.collection('config').get();
    const rows = [];
    snap.forEach(doc => rows.push({ id: doc.id, ...doc.data() }));
    
    if (rows.length) {
      const { error } = await dstClient.from('config').upsert(rows, { onConflict: 'id' });
      if (error) throw error;
      console.log(`  ✅ config: ${rows.length} 条`);
    }
  } catch(e) {
    console.error('  ❌ config:', e);
  }

  // 2. 迁移 punches
  console.log('📦 迁移 punches...');
  try {
    const snap = await fsDb.collection('punches').get();
    const rows = [];
    snap.forEach(doc => rows.push(doc.data()));
    
    if (rows.length) {
      const { error } = await dstClient.from('punches').insert(rows);
      if (error) throw error;
      console.log(`  ✅ punches: ${rows.length} 条`);
    }
  } catch(e) {
    console.error('  ❌ punches:', e);
  }

  // 3. 迁移 claims
  console.log('📦 迁移 claims...');
  try {
    const snap = await fsDb.collection('claims').get();
    const rows = [];
    snap.forEach(doc => rows.push({ id: doc.id, ...doc.data() }));
    
    if (rows.length) {
      const { error } = await dstClient.from('claims').upsert(rows, { onConflict: 'id' });
      if (error) throw error;
      console.log(`  ✅ claims: ${rows.length} 条`);
    }
  } catch(e) {
    console.error('  ❌ claims:', e);
  }

  console.log('\n✅ 反向迁移完成！');
  console.log('运行: switchDBProvider("supabase") 然后刷新页面');
  
  try { fsApp.delete(); } catch(e) {}
}

console.log('数据迁移工具已加载');
console.log('');
console.log('📤 Supabase → Firestore: 运行 migrateSupabaseToFirestore()');
console.log('📥 Firestore → Supabase: 运行 migrateFirestoreToSupabase()');
console.log('');
console.log('⚠️  请先配置脚本中的 FIREBASE_CONFIG！');
