import { ApiKeysSettings } from "./api-keys";
import { BillingSettings } from "./billing";
import { DataSettings } from "./data";
import { FilesSettings } from "./files";
import { GeneralSettings } from "./general";
import { MemorySettings } from "./memory";
import { PersonalizationSettings } from "./personalization";
import { ProfileSettings } from "./profile";
import { SecuritySettings } from "./security";
import { UsageSettings } from "./usage";

/** Every settings section, shared by /settings/[section] and the Quick Chat settings view. */
export const SETTINGS_PAGES: Record<string, () => React.ReactNode> = {
  general: GeneralSettings,
  profile: ProfileSettings,
  personalization: PersonalizationSettings,
  memory: MemorySettings,
  files: FilesSettings,
  data: DataSettings,
  security: SecuritySettings,
  usage: UsageSettings,
  billing: BillingSettings,
  "api-keys": ApiKeysSettings,
};
