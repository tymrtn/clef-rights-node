type StorageKind = "local" | "session";

function browserStorage(kind: StorageKind): Storage | null {
  try {
    return kind === "local" ? globalThis.localStorage : globalThis.sessionStorage;
  } catch {
    return null;
  }
}

export function safeStorageGet(kind: StorageKind, key: string): string | null {
  try {
    return browserStorage(kind)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export function safeStorageSet(kind: StorageKind, key: string, value: string): boolean {
  try {
    const storage = browserStorage(kind);
    if (!storage) return false;
    storage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export function safeStorageRemove(kind: StorageKind, key: string): boolean {
  try {
    const storage = browserStorage(kind);
    if (!storage) return false;
    storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}
