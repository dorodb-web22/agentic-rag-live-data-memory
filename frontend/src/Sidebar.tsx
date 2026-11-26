import { groupConversationsByDate, type SavedConversation } from './chatStorage';

export type HealthState = 'online' | 'offline' | 'mock' | 'checking';

type Props = {
  displayName: string;
  conversations: SavedConversation[];
  activeConversationId: string | null;
  activeView: 'home' | 'chat';
  health: HealthState;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onHome: () => void;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onOpenSettings: () => void;
};

const HEALTH_LABEL: Record<HealthState, string> = {
  online: 'Connected',
  mock: 'Demo mode',
  offline: 'Offline',
  checking: 'Checking…',
};

export default function Sidebar({
  displayName,
  conversations,
  activeConversationId,
  activeView,
  health,
  collapsed,
  onToggleCollapsed,
  onHome,
  onNewChat,
  onSelect,
  onDelete,
  onOpenSettings,
}: Props) {
  const groups = groupConversationsByDate(conversations);

  return (
    <aside
      className={`sidebar${collapsed ? ' sidebar--collapsed' : ''}`}
      aria-label="Primary navigation"
    >
      <div className="sidebar-profile">
        <span className="avatar" aria-hidden="true">
          {displayName.slice(0, 1).toUpperCase()}
        </span>
        <span className="profile-name">{displayName}</span>
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
      </nav>

      <div className="sidebar-history" aria-label="Saved chats">
        {conversations.length === 0 ? (
          <p className="history-empty">
            Your chats are saved here automatically, so you can pick up where you left off.
          </p>
        ) : (
          groups.map((group) => (
            <section key={group.label} className="history-group">
              <h3 className="history-group-label">{group.label}</h3>
              <ul className="history-list">
                {group.items.map((conv) => {
                  const isActive = activeView === 'chat' && conv.id === activeConversationId;
                  return (
                    <li
                      key={conv.id}
                      className={`history-row${isActive ? ' history-row--active' : ''}`}
                      data-testid="history-item"
                    >
                      <button
                        type="button"
                        className="history-open"
                        onClick={() => onSelect(conv.id)}
                        title={conv.title}
                        aria-current={isActive ? 'page' : undefined}
                      >
                        {conv.title}
                      </button>
                      <button
                        type="button"
                        className="history-remove"
                        onClick={() => onDelete(conv.id)}
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
        <div className="trust-card" role="status">
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
