# UniClip — Android Companion Application Guide

**Package Name:** `com.universalclipboard.ai`  
**Root Directory:** `mobile/`  
**Flutter SDK:** 3.47.7 (Dart 3.7+)  
**Target Platform:** Android 15 (API level 35+) / Android 7.0+ (minSdk 23)  
**Firebase Project:** `universal-clipboard-ai`

---

## 1. Overview & Architecture

The UniClip Android companion app provides real-time bidirectional synchronization with your Windows clipboard and Flask web dashboard.

```text
mobile/
├── android/
│   ├── app/
│   │   ├── build.gradle.kts          # App ID: com.universalclipboard.ai, Google Services plugin
│   │   ├── google-services.json      # Firebase configuration for Android client
│   │   └── src/main/
│   │       ├── AndroidManifest.xml   # Internet, Network permissions, App title
│   │       └── kotlin/com/universalclipboard/ai/MainActivity.kt
│   └── settings.gradle.kts           # Google Services & Kotlin Gradle plugins
├── lib/
│   ├── main.dart                     # App entry point, Firebase init, AuthGate, Theme setup
│   ├── models/
│   │   └── clipboard_entry.dart      # Canonical data model adhering to CLIPBOARD_DATA_SCHEMA.md
│   ├── providers/
│   │   └── clipboard_provider.dart   # Multi-select, Select All, Deselect All, Search & Filter state
│   ├── services/
│   │   ├── auth_service.dart         # Google Sign-In & Firebase Auth session management
│   │   └── firestore_service.dart    # Cloud Firestore streaming, hard delete, chunked bulk batch deletes
│   ├── theme/
│   │   └── app_theme.dart            # Material 3 dark & light palettes with custom components
│   ├── widgets/
│   │   └── entry_card.dart           # Interactive card with selection checkbox, retention badge, copy, delete
│   └── screens/
│       ├── login_screen.dart         # Google Sign-In branded authentication UI
│       └── history_screen.dart       # Real-time list, search bar, bulk action banner, full modal
├── test/
│   └── widget_test.dart              # Automated unit tests for canonical model & state provider
└── pubspec.yaml                      # Pinned dependencies (firebase_core, firebase_auth, cloud_firestore, etc.)
```

---

## 2. Canonical Data Contract & 7-Day Retention

All clipboard items are synchronized under:
```text
users/{uid}/clipboardEntries/{entryId}
```

### Document Schema
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `id` | `String` | Stable UUIDv4 string matching Firestore document ID. |
| `user_id` | `String` | Authenticated user's Firebase UID. |
| `content` | `String` | Clipboard text payload (up to 64 KB). Sensitive credentials masked locally. |
| `entry_type` | `String` | Classification: `"text"` or `"url"`. |
| `created_at` | `number` | UTC epoch timestamp in milliseconds. |
| `updated_at` | `number` | UTC epoch timestamp in milliseconds. |
| `expires_at` | `number` | Retention deadline: `created_at + 604,800,000` (strictly 7 days). |
| `schema_version` | `number` | Schema version indicator (`1`). |

### Anti-Resurrection Architecture
- **In-Memory Tombstones**: Deleted IDs are registered instantly in `FirestoreService._deletedTombstones` to avoid visual flicker if local Firestore snapshot caches lag.
- **Batched Deletes**: Bulk deletes are executed in atomic Firestore write batches (max 450 items per chunk, safely below Firestore's 500-operation ceiling).
- **Hard Deletes**: Records are deleted from Firestore; offline caches synchronize on reconnect without resurrecting deleted keys.

---

## 3. Bulk Selection & Operations

1. **Per-Item Checkbox**: Each `EntryCard` contains a Material 3 checkbox. Tapping toggles selection without opening the item preview.
2. **Selection Bar**: When `selectedCount > 0`, a sticky action banner displays:
   - Current count (`N selected`).
   - **Select All**: Selects all currently visible/filtered entries (respects search queries).
   - **Deselect All**: Clears current selection.
   - **Delete Selected**: Prompts with confirmation modal before initiating batch deletion.
3. **Single Deletion**: Trash icon on card prompts user confirmation before deleting.

---

## 4. Running & Verification Commands

### Prerequisites
- Flutter SDK path: `C:\src\flutter\bin`
- Android SDK path: `C:\Users\Nitin\AppData\Local\Android\Sdk`
- Target Device: Realme Narzo 60x 5G (`RMX3782`, Device ID: `MFJVE6HMVSRKIN9D`, Android 15, API 35)

### Run Unit Tests
```powershell
cd mobile
cmd.exe /c "C:\src\flutter\bin\flutter.bat test"
```

### Static Analysis
```powershell
cd mobile
cmd.exe /c "C:\src\flutter\bin\flutter.bat analyze"
```

### Build Debug APK
```powershell
cd mobile
cmd.exe /c "C:\src\flutter\bin\flutter.bat build apk --debug"
```

### Deploy to Connected Phone
```powershell
cd mobile
cmd.exe /c "C:\src\flutter\bin\flutter.bat run -d MFJVE6HMVSRKIN9D"
```
