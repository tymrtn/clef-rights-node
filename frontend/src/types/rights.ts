// Rights Contract Types - policyVersion 2.1

export type UsageState = 'blocked' | 'requires_approval' | 'allowed'
export type RestrictionState = 'allowed' | 'conditional' | 'denied'

export type UsageCategory =
  | 'ads_brand'
  | 'ads_political'
  | 'ads_psa'
  | 'film_tv'
  | 'streaming_visual'
  | 'video_game'
  | 'podcast_audio'
  | 'ugc_creator'
  | 'live_performance'
  | 'background_music'
  | 'corporate_internal'
  | 'educational'
  | 'personal_noncommercial'
  | 'ai_training_recursive'
  | 'derivative_remix'

export type RestrictionCategory =
  | 'political'
  | 'adult'
  | 'alcohol_tobacco_cannabis'
  | 'weapons_defense'
  | 'gambling'
  | 'religion'
  | 'sensitive_social_issues'
  | 'health_pharma'
  | 'children_sensitive'
  | 'likeness_voice_clone'
  | 'deceptive_endorsement'

export interface CategoryMeta {
  id: string
  title: string
  description: string
}

export const USAGE_CATEGORIES: Record<UsageCategory, CategoryMeta> = {
  ads_brand: {
    id: 'ads_brand',
    title: 'Brand Advertising',
    description: 'Commercial advertisements for consumer brands and products',
  },
  ads_political: {
    id: 'ads_political',
    title: 'Political Advertising',
    description: 'Campaign ads, political messaging, or partisan content',
  },
  ads_psa: {
    id: 'ads_psa',
    title: 'Public Service Announcements',
    description: 'Non-profit advocacy and public awareness campaigns',
  },
  film_tv: {
    id: 'film_tv',
    title: 'Film & Television Sync',
    description: 'Synchronization licenses for film, TV, and streaming video content',
  },
  streaming_visual: {
    id: 'streaming_visual',
    title: 'Visual Streaming Platforms',
    description: 'Music videos and visual content on YouTube, Vimeo, etc.',
  },
  video_game: {
    id: 'video_game',
    title: 'Video Games',
    description: 'Interactive entertainment, in-game music, and trailers',
  },
  podcast_audio: {
    id: 'podcast_audio',
    title: 'Podcast & Audio',
    description: 'Podcast intros, outros, background music, and audio storytelling',
  },
  ugc_creator: {
    id: 'ugc_creator',
    title: 'UGC & Creator Content',
    description: 'User-generated content on social platforms (TikTok, Instagram, etc.)',
  },
  live_performance: {
    id: 'live_performance',
    title: 'Live Performance',
    description: 'Live events, concerts, DJ sets, and public performances',
  },
  background_music: {
    id: 'background_music',
    title: 'Background Music',
    description: 'Retail, hospitality, events, and ambient music services',
  },
  corporate_internal: {
    id: 'corporate_internal',
    title: 'Corporate & Internal Use',
    description: 'Internal corporate videos, presentations, and training materials',
  },
  educational: {
    id: 'educational',
    title: 'Educational Use',
    description: 'Schools, universities, tutorials, and non-commercial learning content',
  },
  personal_noncommercial: {
    id: 'personal_noncommercial',
    title: 'Personal & Non-Commercial',
    description: 'Personal projects, home videos, and non-monetized content',
  },
  ai_training_recursive: {
    id: 'ai_training_recursive',
    title: 'Recursive AI Training',
    description: 'Using AI-generated output to train future AI models',
  },
  derivative_remix: {
    id: 'derivative_remix',
    title: 'Derivative Works & Remixes',
    description: 'Remixes, mashups, covers, and transformative derivative works',
  },
}

export const RESTRICTION_CATEGORIES: Record<RestrictionCategory, CategoryMeta> = {
  political: {
    id: 'political',
    title: 'Political Content',
    description: 'Political campaigns, partisan messaging, or ideological advocacy',
  },
  adult: {
    id: 'adult',
    title: 'Adult Content',
    description: 'Sexually explicit or adult-oriented content (18+)',
  },
  alcohol_tobacco_cannabis: {
    id: 'alcohol_tobacco_cannabis',
    title: 'Alcohol, Tobacco & Cannabis',
    description: 'Promotion of alcoholic beverages, tobacco products, or cannabis',
  },
  weapons_defense: {
    id: 'weapons_defense',
    title: 'Weapons & Defense',
    description: 'Firearms, military equipment, or defense industry content',
  },
  gambling: {
    id: 'gambling',
    title: 'Gambling & Gaming',
    description: 'Casinos, sports betting, lotteries, and gambling services',
  },
  religion: {
    id: 'religion',
    title: 'Religious Content',
    description: 'Religious messaging, faith-based content, or spiritual advocacy',
  },
  sensitive_social_issues: {
    id: 'sensitive_social_issues',
    title: 'Sensitive Social Issues',
    description: 'Controversial topics including race, gender, social justice movements',
  },
  health_pharma: {
    id: 'health_pharma',
    title: 'Health & Pharmaceutical',
    description: 'Medical products, pharmaceuticals, or health-related advertising',
  },
  children_sensitive: {
    id: 'children_sensitive',
    title: 'Children-Sensitive Content',
    description: 'Content targeting or involving children under 13',
  },
  likeness_voice_clone: {
    id: 'likeness_voice_clone',
    title: 'Voice & Likeness Cloning',
    description: 'AI voice cloning, deepfakes, or synthetic likeness generation',
  },
  deceptive_endorsement: {
    id: 'deceptive_endorsement',
    title: 'Deceptive Endorsements',
    description: 'False endorsements or misleading artist association claims',
  },
}

export const USAGE_KEYS = Object.keys(USAGE_CATEGORIES) as UsageCategory[]
export const RESTRICTION_KEYS = Object.keys(RESTRICTION_CATEGORIES) as RestrictionCategory[]

export type ReadinessState = 'ready' | 'warning' | 'disabled' | 'missing' | 'stale' | 'blocked'

export interface NodeReadinessCheck {
  key: string
  status: ReadinessState
  required: boolean
  summary: string
  remediation?: string
  details: Record<string, unknown>
}

export interface NodeReadiness {
  ready: boolean
  deploymentMode: string
  checkedAt: string
  checks: NodeReadinessCheck[]
}

export type OnboardingState = 'complete' | 'in_progress' | 'pending' | 'not_applicable'

export interface OrganizationOnboardingMilestone {
  key: string
  status: OnboardingState
  summary: string
  action?: string
  count: number
}

export interface OrganizationOnboardingStatus {
  organizationId: string
  organizationType: string
  complete: boolean
  completedCount: number
  applicableCount: number
  milestones: OrganizationOnboardingMilestone[]
}
