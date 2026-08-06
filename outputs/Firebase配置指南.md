## Firebase 配置指南（3分钟完成）

### 第一步：创建 Firebase 项目
1. 打开 https://console.firebase.google.com
2. 点击「添加项目」→ 输入名称（如"考勤打卡"）→ 创建

### 第二步：创建 Firestore 数据库
1. 左侧菜单 → 「Firestore Database」→ 「创建数据库」
2. 选择「以测试模式启动」→ 选择位置（选 asia-east1 或 asia-southeast1）→ 启用

### 第三步：获取配置信息
1. 点击左上角 ⚙️ → 「项目设置」
2. 底部「你的应用」区域 → 点击 `</>` 网页图标
3. 输入应用名称（如"ClockIn"）→ 注册应用
4. 复制显示的 `firebaseConfig` 对象，类似：

```js
const firebaseConfig = {
  apiKey: "AIzaSy...",
  authDomain: "xxx.firebaseapp.com",
  projectId: "xxx",
  storageBucket: "xxx.appspot.com",
  messagingSenderId: "123456",
  appId: "1:123456:web:abcdef"
};
```

### 第四步：填入配置
打开 `index.html`，找到顶部的 `firebaseConfig` 变量，替换为你的配置即可。

### 第五步：设置安全规则（可选但推荐）
在 Firestore 控制台 → 「规则」标签页 → 粘贴以下规则：

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      allow read, write: if true;
    }
  }
}
```

完成后所有设备打开同一个链接就能实时同步了。
