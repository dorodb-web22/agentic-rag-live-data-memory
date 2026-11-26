import { useEffect, useState } from 'react';
import type { AuthUser } from './auth';
import { groupConversationsByDate, type SavedConversation } from './chatStorage';

export type HealthState = 'online' | 'offline' | 'checking';

type Props = {
  user: AuthUser;
  conversations: SavedConversation[];
  activeThreadId: string | null;
  activeView: 'home' | 'chat';
  health: HealthState;
  connectedIntegrationsCount?: number;
  needsReauthCount?: number;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onHome: () => void;
  onNewChat: () => void;
  onSelect: (threadId: string) => void;
  onDelete: (threadId: string) => void;
  onOpenIntegrations: () => void;
  onOpenSettings: () => void;
};

const HEALTH_LABEL: Record<HealthState, string> = {
  online: 'Connected',
  offline: 'Offline',
  checking: 'Checking…',
};

export default function Sidebar({
  user,
  conversations,
  activeThreadId,
  activeView,
  health,
  connectedIntegrationsCount = 0,
  needsReauthCount = 0,
  collapsed,
  onToggleCollapsed,
  onHome,
  onNewChat,
  onSelect,
  onDelete,
  onOpenIntegrations,
  onOpenSettings,
}: Props) {
  const [avatarError, setAvatarError] = useState(false);

  useEffect(() => {
    setAvatarError(false);
  }, [user.picture]);

  const groups = groupConversationsByDate(conversations);
  const initial = (user.name || user.email || '?').trim().slice(0, 1).toUpperCase();
  const showPicture = Boolean(user.picture) && !avatarError;

  return (
    <aside
      className={`sidebar${collapsed ? ' sidebar--collapsed' : ''}`}
      aria-label="Primary navigation"
    >
      <div className="sidebar-profile">
        {showPicture ? (
          <img
            className="avatar avatar--img"
            src={user.picture!}
            alt={user.name}
            referrerPolicy="no-referrer"
            onError={() => setAvatarError(true)}
            data-testid="user-avatar-img"
          />
        ) : (
          <span className="avatar" aria-hidden="true" data-testid="user-avatar-fallback">
            {initial}
          </span>
        )}
        <div className="profile-meta">
          <span className="profile-name" title={user.name}>
            {user.name}
          </span>
          <span className="profile-email" title={user.email}>
            {user.email}
          </span>
        </div>
        <button
          type="button"
          className="icon-btn"
          onClick={onToggleCollapsed}
          aria-label="Collapse sidebar"
          title="Collapse sidebar"
        >
          «
        </button>
      </div>

      <nav className="sidebar-nav" aria-label="Main">
        <button
          type="button"
          className={`nav-item${activeView === 'home' ? ' nav-item--active' : ''}`}
          onClick={onHome}
        >
          <span>Home</span>
          <span className="nav-glyph" aria-hidden="true">⌂</span>
        </button>
        <button type="button" className="nav-item" onClick={onNewChat}>
          <span>New chat</span>
          <span className="nav-glyph" aria-hidden="true">＋</span>
        </button>
        <button
          type="button"
          className="nav-item"
          onClick={onOpenIntegrations}
          data-testid="sidebar-integrations-btn"
        >
          <span>Integrations</span>
          {needsReauthCount > 0 ? (
            <span className="chip-tag chip-tag--warn">Reconnect</span>
          ) : connectedIntegrationsCount > 0 ? (
            <span className="badge">{connectedIntegrationsCount}</span>
          ) : (
            <span className="nav-glyph" aria-hidden="true">⇄</span>
          )}
        </button>
      </nav>

      <div className="sidebar-history" aria-label="Saved chats">
        {conversations.length === 0 ? (
          <p className="history-empty">
            Your chats are saved to your account automatically, so you can pick up on any device.
          </p>
        ) : (
          groups.map((group) => (
            <section key={group.label} className="history-group">
              <h3 className="history-group-label">{group.label}</h3>
              <ul className="history-list">
                {group.items.map((conv) => {
                  const key = conv.threadId ?? conv.id;
                  const isActive =
                    activeView === 'chat' &&
                    Boolean(activeThreadId) &&
                    conv.threadId === activeThreadId;
                  return (
                    <li
                      key={key}
                      className={`history-row${isActive ? ' history-row--active' : ''}`}
                      data-testid="history-item"
                    >
                      <button
                        type="button"
                        className="history-open"
                        onClick={() => {
                          if (conv.threadId) onSelect(conv.threadId);
                        }}
                        title={conv.title}
                        aria-current={isActive ? 'page' : undefined}
                      >
                        {conv.title}
                      </button>
                      <button
                        type="button"
                        className="history-remove"
                        onClick={() => {
                          if (conv.threadId) onDelete(conv.threadId);
                        }}
                        aria-label={`Delete chat: ${conv.title}`}
                        title="Delete chat"
                      >
                        ×
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))
        )}
      </div>

      <div className="sidebar-footer">
        <div className="trust-card" role="status" data-testid="health-status">
          <span className={`health-dot health-dot--${health}`} aria-hidden="true" />
          <div>
            <strong>{HEALTH_LABEL[health]}</strong>
            <span>Read-only data access · answers cite sources</span>
          </div>
        </div>
        <button type="button" className="nav-item nav-item--settings" onClick={onOpenSettings}>
          <span>Settings</span>
          <span className="nav-glyph" aria-hidden="true">⚙</span>
        </button>
      </div>
    </aside>
  );
}
