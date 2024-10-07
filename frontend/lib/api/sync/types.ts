import { UUID } from "crypto";

import { Brain } from "@/lib/context/BrainProvider/types";

export type Provider = "Google" | "Azure" | "DropBox" | "Notion" | "GitHub";

export type Integration =
  | "Google Drive"
  | "Share Point"
  | "Dropbox"
  | "Notion"
  | "GitHub";

export type SyncStatus = "SYNCING" | "SYNCED" | "ERROR" | "REMOVED";

export type KnowledgeStatus =
  | "ERROR"
  | "RESERVED"
  | "PROCESSING"
  | "PROCESSED"
  | "UPLOADED";

export interface KMSElement {
  brains: Brain[];
  id: UUID;
  file_name?: string;
  sync_file_id: string | null;
  is_folder: boolean;
  icon?: string;
  sync_id: number | null;
  parent_id: string | null;
  parentKMSElement?: KMSElement;
  fromProvider?: SyncsByProvider;
  source: "local" | string;
  last_synced_at: string;
  url?: string;
  extension?: string;
  status?: KnowledgeStatus;
  file_sha1?: string;
  source_link?: string;
  metadata?: string;
}

interface Credentials {
  token: string;
}

export interface Sync {
  name: string;
  provider: Provider;
  id: number;
  credentials: Credentials;
  email: string;
  status: SyncStatus;
}

export interface SyncsByProvider {
  provider: Provider;
  syncs: Sync[];
}

export interface SyncSettings {
  folders?: string[];
  files?: string[];
}

export interface ActiveSync {
  id: number;
  name: string;
  syncs_user_id: number;
  user_id: string;
  settings: SyncSettings;
  last_synced: string;
  sync_interval_minutes: number;
  brain_id: string;
  syncs_user: {
    provider: Provider;
  };
}

export interface OpenedConnection {
  user_sync_id: number;
  id: number | undefined;
  provider: Provider;
  submitted: boolean;
  selectedFiles: KMSElement[];
  name: string;
  last_synced: string;
  cleaned?: boolean;
}
