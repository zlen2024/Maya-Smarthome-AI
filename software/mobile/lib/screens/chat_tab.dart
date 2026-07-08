import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import '../services/api_service.dart';

/// WhatsApp-style chat tab for house members.
class ChatTab extends StatefulWidget {
  const ChatTab({super.key});

  @override
  State<ChatTab> createState() => _ChatTabState();
}

class _ChatTabState extends State<ChatTab> {
  final List<Map<String, dynamic>> _messages = [];
  final TextEditingController _textCtrl = TextEditingController();
  final ScrollController _scrollCtrl = ScrollController();
  StreamSubscription<Map<String, dynamic>>? _chatSub;
  bool _loadingHistory = false;
  bool _hasMore = true;
  bool _initialLoaded = false;

  // ── Mentions ────────────────────────────────────────────────────
  List<Map<String, dynamic>> _mentionables = [];
  Set<int> _unseenMentionIds = {};
  List<Map<String, dynamic>> _suggestions = [];

  /// The current user identifier for styling own messages
  int? get _currentUserId => ApiService.accId;

  @override
  void initState() {
    super.initState();
    _loadHistory();
    _initMentions();
    _chatSub = ApiService.chatBroadcasts.listen(_onChatMessage);
    _scrollCtrl.addListener(_onScroll);
    _textCtrl.addListener(_onTextChanged);
  }

  @override
  void dispose() {
    _chatSub?.cancel();
    _textCtrl.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  // ── Mention setup: load names, capture unseen for highlight, mark seen ──
  Future<void> _initMentions() async {
    final houseId = ApiService.houseId;
    if (houseId == null) return;
    try {
      _mentionables = await ApiService.getMentionables(houseId);
    } catch (_) {}
    try {
      final unseen = await ApiService.getUnseenMentions(houseId);
      _unseenMentionIds = ((unseen['msg_ids'] ?? []) as List)
          .map((e) => e as int)
          .toSet();
    } catch (_) {}
    if (mounted) setState(() {});
    // Opening the chat clears the marks; keep the ids above only to highlight
    // this session so the reader can spot them before they fade next time.
    try {
      await ApiService.markMentionsSeen(houseId);
      ApiService.emitMentionsChanged();
    } catch (_) {}
  }

  // ── '@' autocomplete ────────────────────────────────────────────
  void _onTextChanged() {
    final sel = _textCtrl.selection.baseOffset;
    final text = _textCtrl.text;
    if (sel < 0) {
      if (_suggestions.isNotEmpty) setState(() => _suggestions = []);
      return;
    }
    // Find an '@token' immediately before the cursor (no whitespace inside).
    final upToCursor = text.substring(0, sel);
    final at = upToCursor.lastIndexOf('@');
    if (at == -1 || (at > 0 && !_isBoundary(upToCursor[at - 1]))) {
      if (_suggestions.isNotEmpty) setState(() => _suggestions = []);
      return;
    }
    final partial = upToCursor.substring(at + 1);
    if (partial.contains(RegExp(r'\s'))) {
      if (_suggestions.isNotEmpty) setState(() => _suggestions = []);
      return;
    }
    final p = partial.toLowerCase();
    final matches = _mentionables
        .where((m) => (m['name'] as String).toLowerCase().startsWith(p))
        .take(6)
        .toList();
    setState(() => _suggestions = matches);
  }

  bool _isBoundary(String ch) => ch == ' ' || ch == '\n' || ch == '\t';

  void _insertMention(String name) {
    final sel = _textCtrl.selection.baseOffset;
    final text = _textCtrl.text;
    final upToCursor = text.substring(0, sel);
    final at = upToCursor.lastIndexOf('@');
    if (at == -1) return;
    final newText = '${text.substring(0, at)}@$name ${text.substring(sel)}';
    final newOffset = at + name.length + 2; // '@' + name + trailing space
    _textCtrl.value = TextEditingValue(
      text: newText,
      selection: TextSelection.collapsed(offset: newOffset),
    );
    setState(() => _suggestions = []);
  }

  // ── Load Chat History ──────────────────────────────────────────
  Future<void> _loadHistory({int? before}) async {
    if (_loadingHistory) return;
    final houseId = ApiService.houseId;
    if (houseId == null) return;

    setState(() => _loadingHistory = true);
    try {
      final result =
          await ApiService.getChatHistory(houseId, before: before);
      final msgs = (result['messages'] as List)
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
      _hasMore = result['has_more'] == true;

      setState(() {
        if (before != null) {
          // Prepend older messages
          _messages.insertAll(0, msgs);
        } else {
          _messages.clear();
          _messages.addAll(msgs);
        }
        _initialLoaded = true;
      });

      // Scroll to bottom on initial load
      if (before == null) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          _scrollToBottom();
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Failed to load chat: ${e.toString().replaceFirst("Exception: ", "")}'),
          behavior: SnackBarBehavior.floating,
        ));
      }
    } finally {
      if (mounted) setState(() => _loadingHistory = false);
    }
  }

  // ── Handle incoming chat broadcast ─────────────────────────────
  void _onChatMessage(Map<String, dynamic> data) {
    if (!mounted) return;
    if (data['type'] == 'chat_cleared') {
      setState(() {
        _messages.clear();
        _unseenMentionIds = {};
        _hasMore = false;
      });
      return;
    }
    setState(() => _messages.add(data));
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _scrollToBottom();
    });
  }

  // ── Scroll handling ────────────────────────────────────────────
  void _onScroll() {
    // Load older messages when scrolled to the top
    if (_scrollCtrl.position.pixels <=
            _scrollCtrl.position.minScrollExtent + 50 &&
        _hasMore &&
        !_loadingHistory &&
        _messages.isNotEmpty) {
      final oldestId = _messages.first['msg_id'] as int?;
      if (oldestId != null) {
        _loadHistory(before: oldestId);
      }
    }
  }

  void _scrollToBottom() {
    if (_scrollCtrl.hasClients) {
      _scrollCtrl.animateTo(
        _scrollCtrl.position.maxScrollExtent,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    }
  }

  // ── Send message ───────────────────────────────────────────────
  void _sendMessage() {
    final text = _textCtrl.text.trim();
    if (text.isEmpty) return;

    final channel = ApiService.activeChannel;
    if (channel == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Not connected — message not sent'),
        behavior: SnackBarBehavior.floating,
      ));
      return;
    }

    channel.sink.add(jsonEncode({
      'type': 'chat',
      'message': text,
    }));
    _textCtrl.clear();
  }

  // ── Build ──────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;

    return Column(
      children: [
        // Message list
        Expanded(
          child: !_initialLoaded
              ? const Center(child: CircularProgressIndicator())
              : _messages.isEmpty
                  ? Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.chat_bubble_outline_rounded,
                              size: 56, color: cs.onSurfaceVariant.withOpacity(0.4)),
                          const SizedBox(height: 12),
                          Text('No messages yet',
                              style: tt.bodyLarge?.copyWith(
                                  color: cs.onSurfaceVariant)),
                          const SizedBox(height: 4),
                          Text('Start the conversation!',
                              style: tt.bodySmall?.copyWith(
                                  color: cs.onSurfaceVariant.withOpacity(0.6))),
                        ],
                      ),
                    )
                  : ListView.builder(
                      controller: _scrollCtrl,
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 8),
                      itemCount: _messages.length + (_loadingHistory ? 1 : 0),
                      itemBuilder: (context, index) {
                        if (_loadingHistory && index == 0) {
                          return const Padding(
                            padding: EdgeInsets.all(12),
                            child: Center(
                                child:
                                    SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))),
                          );
                        }
                        final msgIndex =
                            _loadingHistory ? index - 1 : index;
                        final m = _messages[msgIndex];
                        return _MessageBubble(
                          message: m,
                          isOwn: _isOwnMessage(m),
                          isAi: m['sender_type'] == 'ai',
                          isMention: _unseenMentionIds.contains(m['msg_id']),
                        );
                      },
                    ),
        ),

        // '@' mention suggestions
        if (_suggestions.isNotEmpty)
          Container(
            constraints: const BoxConstraints(maxHeight: 180),
            decoration: BoxDecoration(
              color: cs.surfaceContainerHigh,
              border: Border(top: BorderSide(color: cs.outlineVariant, width: 0.5)),
            ),
            child: ListView(
              shrinkWrap: true,
              padding: EdgeInsets.zero,
              children: _suggestions.map((m) {
                final isAi = m['type'] == 'ai';
                return ListTile(
                  dense: true,
                  leading: CircleAvatar(
                    radius: 14,
                    backgroundColor:
                        isAi ? cs.tertiaryContainer : cs.primaryContainer,
                    child: Icon(
                      isAi
                          ? Icons.auto_awesome
                          : m['type'] == 'child'
                              ? Icons.child_care_rounded
                              : Icons.person_rounded,
                      size: 15,
                      color: isAi ? cs.onTertiaryContainer : cs.onPrimaryContainer,
                    ),
                  ),
                  title: Text(m['name'] as String,
                      style: tt.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
                  subtitle: isAi
                      ? Text('AI assistant',
                          style: tt.labelSmall?.copyWith(color: cs.tertiary))
                      : null,
                  onTap: () => _insertMention(m['name'] as String),
                );
              }).toList(),
            ),
          ),

        // Input bar
        Container(
          decoration: BoxDecoration(
            color: cs.surfaceContainerHigh,
            border: Border(
              top: BorderSide(color: cs.outlineVariant, width: 0.5),
            ),
          ),
          padding: EdgeInsets.only(
            left: 12,
            right: 4,
            top: 8,
            bottom: MediaQuery.of(context).padding.bottom + 8,
          ),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _textCtrl,
                  textCapitalization: TextCapitalization.sentences,
                  maxLines: 4,
                  minLines: 1,
                  onSubmitted: (_) => _sendMessage(),
                  decoration: InputDecoration(
                    hintText: 'Type a message...',
                    filled: true,
                    fillColor: cs.surfaceContainerLow,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(24),
                      borderSide: BorderSide.none,
                    ),
                    contentPadding: const EdgeInsets.symmetric(
                        horizontal: 16, vertical: 10),
                    isDense: true,
                  ),
                ),
              ),
              const SizedBox(width: 4),
              IconButton.filled(
                onPressed: _sendMessage,
                icon: const Icon(Icons.send_rounded, size: 20),
                style: IconButton.styleFrom(
                  backgroundColor: cs.primary,
                  foregroundColor: cs.onPrimary,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  bool _isOwnMessage(Map<String, dynamic> msg) {
    final senderId = msg['sender_id'];
    final senderType = msg['sender_type'];
    if (ApiService.isChild) {
      return senderType == 'child' && senderId == _currentUserId;
    }
    return senderType == 'parent' && senderId == _currentUserId;
  }
}

// ── Message Bubble ─────────────────────────────────────────────────
class _MessageBubble extends StatelessWidget {
  final Map<String, dynamic> message;
  final bool isOwn;
  final bool isAi;
  final bool isMention;

  const _MessageBubble({
    required this.message,
    required this.isOwn,
    this.isAi = false,
    this.isMention = false,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;
    final senderName = message['sender_name'] ?? 'Unknown';
    final text = message['message'] ?? '';
    final timestamp = message['timestamp'] ?? '';

    // Format timestamp
    String timeStr = '';
    try {
      final dt = DateTime.parse(timestamp).toLocal();
      timeStr =
          '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
    } catch (_) {}

    return Align(
      alignment: isOwn ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: EdgeInsets.only(
          top: 4,
          bottom: 4,
          left: isOwn ? 60 : 0,
          right: isOwn ? 0 : 60,
        ),
        child: Column(
          crossAxisAlignment:
              isOwn ? CrossAxisAlignment.end : CrossAxisAlignment.start,
          children: [
            if (!isOwn)
              Padding(
                padding: const EdgeInsets.only(left: 12, bottom: 2),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (isAi) ...[
                      Icon(Icons.auto_awesome,
                          size: 12, color: cs.tertiary),
                      const SizedBox(width: 4),
                    ],
                    Text(
                      senderName,
                      style: tt.labelSmall?.copyWith(
                        color: isAi ? cs.tertiary : cs.primary,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
            Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: isOwn
                    ? cs.primary
                    : isAi
                        ? cs.tertiaryContainer
                        : cs.surfaceContainerHigh,
                border: isMention
                    ? Border.all(color: cs.secondary, width: 2)
                    : null,
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(18),
                  topRight: const Radius.circular(18),
                  bottomLeft:
                      isOwn ? const Radius.circular(18) : Radius.zero,
                  bottomRight:
                      isOwn ? Radius.zero : const Radius.circular(18),
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    text,
                    style: tt.bodyMedium?.copyWith(
                      color: isOwn
                          ? cs.onPrimary
                          : isAi
                              ? cs.onTertiaryContainer
                              : cs.onSurface,
                    ),
                  ),
                  if (timeStr.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      timeStr,
                      style: tt.labelSmall?.copyWith(
                        fontSize: 10,
                        color: isOwn
                            ? cs.onPrimary.withOpacity(0.7)
                            : isAi
                                ? cs.onTertiaryContainer.withOpacity(0.7)
                                : cs.onSurfaceVariant,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
