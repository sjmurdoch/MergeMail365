---
layout: Conceptual
monikers:
- graph-rest-1.0
defaultMoniker: graph-rest-1.0
versioningType: Ranged
title: message resource type - Microsoft Graph v1.0 | Microsoft Learn
canonicalUrl: https://learn.microsoft.com/en-us/graph/api/resources/message?view=graph-rest-1.0
config_moniker_range: '>= graph-rest-1.0'
feedback_system: Standard
feedback_product_url: https://developer.microsoft.com/graph/support
author: SuryaLashmiS
ms.author: MSGraphDocsVteam
ms.suite: microsoft-graph
ms.subservice: outlook
uhfHeaderId: MSDocsHeader-MSGraph
toc_preview: true
recommendations: false
breadcrumb_path: /graph/ref-breadcrumb/toc.json
ms.service: microsoft-graph
ms.topic: reference
description: A message in a mailFolder.
ms.localizationpriority: high
doc_type: resourcePageType
ms.date: 2024-08-23T00:00:00.0000000Z
locale: en-us
document_id: 1dd382e4-95b6-3ccf-6a15-02d0cc7ed841
document_version_independent_id: 276cebbe-10bc-100e-f9b1-51b2ba30c64b
updated_at: 2025-10-24T02:01:00.0000000Z
original_content_git_url: https://github.com/microsoftgraph/microsoft-graph-docs/blob/live/api-reference/v1.0/resources/message.md
gitcommit: https://github.com/microsoftgraph/microsoft-graph-docs/blob/5415223b47ed33850e96b1d8511f44c5210fcbfa/api-reference/v1.0/resources/message.md
git_commit_id: 5415223b47ed33850e96b1d8511f44c5210fcbfa
default_moniker: graph-rest-1.0
site_name: Docs
depot_name: MSDN.microsoft-graph-ref
page_type: conceptual
toc_rel: ../toc.json
feedback_help_link_type: ''
feedback_help_link_url: ''
word_count: 1623
asset_id: api/resources/message
moniker_range_name: 107bf06837724705de50667b407c0197
monikers:
- graph-rest-1.0
item_type: Content
source_path: api-reference/v1.0/resources/message.md
cmProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/5fc61396-d075-4560-aece-fdbda73d243f
- https://authoring-docs-microsoft.poolparty.biz/devrel/cf9b82c5-b6dc-45f3-b005-b1bc5fc03bea
- https://authoring-docs-microsoft.poolparty.biz/devrel/540ac133-a371-4dbb-8f94-28d6cc77a70b
spProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/ad9437c1-8cda-4537-ad69-b4b263652e13
- https://authoring-docs-microsoft.poolparty.biz/devrel/0c85d34e-bfd2-4466-957c-f0b61e9692df
- https://authoring-docs-microsoft.poolparty.biz/devrel/60bfc045-f127-4841-9d00-ea35495a5800
platformId: 1b8b2edb-db60-84e1-9df8-46e3f3ca61fb
---

# message resource type - Microsoft Graph v1.0 | Microsoft Learn

Namespace: microsoft.graph

A message in a mailFolder.

The maximum total number of recipients included in the **toRecipients**, **ccRecipients**, and **bccRecipients** properties for a single email message sent from an Exchange Online mailbox is 500. For more information, see [sending limits](/en-us/office365/servicedescriptions/exchange-online-service-description/exchange-online-limits#sending-limits).

This resource supports:

- Adding your own data as custom Internet message headers. Add custom headers only when creating a message, and name them starting with "x-". After the message is sent, you cannot modify the headers. To get the headers of a message, apply the `$select` query parameter in a [get message](../message-get) operation.
- Adding your own data as custom properties as [extensions](/en-us/graph/extensibility-overview).
- Subscribing to [change notifications](/en-us/graph/change-notifications-overview).
- Using [delta query](/en-us/graph/delta-query-overview) to track incremental additions, deletions, and updates, by providing a [delta](../message-delta) function.

## Methods

| Method | Return type | Description |
| --- | --- | --- |
| [List messages](../user-list-messages) | [message](message) collection | Get all the messages in the signed-in user's mailbox (including the Deleted Items and Clutter folders). |
| [Create draft message](../user-post-messages) | [message](message) | [Create](../user-post-messages#request-1) a draft of a new message. |
| [Get message](../message-get) | [message](message) | Read properties and relationships of message object. |
| [Update message](../message-update) | [message](message) | Update message object. |
| [Delete message](../message-delete) | None | Delete message object. |
| [Copy message](../message-copy) | [Message](message) | Copy a message to a folder. |
| [Create draft to forward message](../message-createforward) | [Message](message) | Create a draft of the Forward message. You can then [update](../message-update) or [send](../message-send) the draft. |
| [Create draft to reply](../message-createreply) | [Message](message) | Create a draft of the Reply message. You can then [update](../message-update) or [send](../message-send) the draft. |
| [Create draft to reply-all](../message-createreplyall) | [Message](message) | Create a draft of the Reply All message. You can then [update](../message-update) or [send](../message-send) the draft. |
| [Get message delta](../message-delta) | [message](message) collection | Get a set of messages that were added, deleted, or updated in a specified folder. |
| [Forward message](../message-forward) | None | Forward a message. The message is then saved in the Sent Items folder. |
| [Move message](../message-move) | [Message](message) | Move the message to a folder. This creates a new copy of the message in the destination folder. |
| [Reply to a message](../message-reply) | None | Reply to the sender of a message. The message is then saved in the Sent Items folder. |
| [Reply-all to a message](../message-replyall) | None | Reply to all recipients of a message. The message is then saved in the Sent Items folder. |
| [Send draft message](../message-send) | None | Sends a previously created message draft. The message is then saved in the Sent Items folder. |
| [Permanently delete](../message-permanentdelete) | None | Permanently delete a message and place it in the purges folder in the recoverable Items folder in the user's mailbox. |
| **Attachments** |  |  |
| [List attachments](../message-list-attachments) | [Attachment](attachment) collection | Gets all attachments on a message. |
| [Add attachment](../message-post-attachments) | [Attachment](attachment) | Add a new attachment to a message by posting to the attachments collection. |
| **Open extensions** |  |  |
| [Create open extension](../opentypeextension-post-opentypeextension) | [openTypeExtension](opentypeextension) | Create an open extension and add custom properties in a new or existing instance of a resource. |
| [Get open extension](../opentypeextension-get) | [openTypeExtension](opentypeextension) collection | Get an open extension object or objects identified by name or fully qualified name. |
| **Extended properties** |  |  |
| [Create single-value property](../singlevaluelegacyextendedproperty-post-singlevalueextendedproperties) | [message](message) | Create one or more single-value extended properties in a new or existing message. |
| [Get single-value property](../singlevaluelegacyextendedproperty-get) | [message](message) | Get messages that contain a single-value extended property by using `$expand` or `$filter`. |
| [Create multi-value property](../multivaluelegacyextendedproperty-post-multivalueextendedproperties) | [message](message) | Create one or more multi-value extended properties in a new or existing message. |
| [Get multi-value property](../multivaluelegacyextendedproperty-get) | [message](message) | Get a message that contains a multi-value extended property by using `$expand`. |

## Properties

| Property | Type | Description |
| --- | --- | --- |
| bccRecipients | [recipient](recipient) collection | The Bcc: recipients for the message. |
| body | [itemBody](itembody) | The body of the message. It can be in HTML or text format. Find out about [safe HTML in a message body](/en-us/graph/outlook-create-send-messages#reading-messages-with-control-over-the-body-format-returned). |
| bodyPreview | String | The first 255 characters of the message body. It is in text format. |
| ccRecipients | [recipient](recipient) collection | The Cc: recipients for the message. |
| changeKey | String | The version of the message. |
| conversationId | String | The ID of the conversation the email belongs to. |
| conversationIndex | Edm.Binary | Indicates the position of the message within the conversation. |
| createdDateTime | DateTimeOffset | The date and time the message was created.  The date and time information uses ISO 8601 format and is always in UTC time. For example, midnight UTC on Jan 1, 2014 is `2014-01-01T00:00:00Z`. |
| flag | [followupFlag](followupflag) | Indicates the status, start date, due date, or completion date for the message. |
| from | [recipient](recipient) | The owner of the mailbox from which the message is sent. In most cases, this value is the same as the **sender** property, except for sharing or delegation scenarios. The value must correspond to the actual mailbox used. Find out more about [setting the from and sender properties](/en-us/graph/outlook-create-send-messages#setting-the-from-and-sender-properties) of a message. |
| hasAttachments | Boolean | Indicates whether the message has attachments. This property doesn't include inline attachments, so if a message contains only inline attachments, this property is false. To verify the existence of inline attachments, parse the **body** property to look for a `src` attribute, such as `<IMG src="cid:image001.jpg@01D26CD8.6C05F070">`. |
| id | String | Unique identifier for the message. By default, this value changes when the item is moved from one container (such as a folder or calendar) to another. To change this behavior, use the `Prefer: IdType="ImmutableId"` header. See [Get immutable identifiers for Outlook resources](/en-us/graph/outlook-immutable-id) for more information. Read-only. |
| importance | importance | The importance of the message. The possible values are: `low`, `normal`, and `high`. |
| inferenceClassification | inferenceClassificationType | The classification of the message for the user, based on inferred relevance or importance, or on an explicit override. The possible values are: `focused` or `other`. |
| internetMessageHeaders | [internetMessageHeader](internetmessageheader) collection | A collection of message headers defined by [RFC5322](https://www.ietf.org/rfc/rfc5322.txt). The set includes message headers indicating the network path taken by a message from the sender to the recipient. It can also contain custom message headers that hold app data for the message.  Returned only on applying a `$select` query option. Read-only. |
| internetMessageId | String | The message ID in the format specified by [RFC2822](https://www.ietf.org/rfc/rfc2822.txt). |
| isDeliveryReceiptRequested | Boolean | Indicates whether a read receipt is requested for the message. |
| isDraft | Boolean | Indicates whether the message is a draft. A message is a draft if it hasn't been sent yet. |
| isRead | Boolean | Indicates whether the message has been read. |
| isReadReceiptRequested | Boolean | Indicates whether a read receipt is requested for the message. |
| lastModifiedDateTime | DateTimeOffset | The date and time the message was last changed.  The date and time information uses ISO 8601 format and is always in UTC time. For example, midnight UTC on Jan 1, 2014 is `2014-01-01T00:00:00Z`. |
| parentFolderId | String | The unique identifier for the message's parent mailFolder. |
| receivedDateTime | DateTimeOffset | The date and time the message was received.  The date and time information uses ISO 8601 format and is always in UTC time. For example, midnight UTC on Jan 1, 2014 is `2014-01-01T00:00:00Z`. |
| replyTo | [recipient](recipient) collection | The email addresses to use when replying. |
| sender | [recipient](recipient) | The account that is used to generate the message. In most cases, this value is the same as the **from** property. You can set this property to a different value when sending a message from a [shared mailbox](/en-us/exchange/collaboration/shared-mailboxes/shared-mailboxes), [for a shared calendar, or as a delegate](/en-us/graph/outlook-share-or-delegate-calendar). In any case, the value must correspond to the actual mailbox used. Find out more about [setting the from and sender properties](/en-us/graph/outlook-create-send-messages#setting-the-from-and-sender-properties) of a message. |
| sentDateTime | DateTimeOffset | The date and time the message was sent.  The date and time information uses ISO 8601 format and is always in UTC time. For example, midnight UTC on Jan 1, 2014 is `2014-01-01T00:00:00Z`. |
| subject | String | The subject of the message. |
| toRecipients | [recipient](recipient) collection | The To: recipients for the message. |
| uniqueBody | [itemBody](itembody) | The part of the body of the message that is unique to the current message. **uniqueBody** is not returned by default but can be retrieved for a given message by use of the `?$select=uniqueBody` query. It can be in HTML or text format. |
| webLink | String | The URL to open the message in Outlook on the web.You can append an `ispopout` argument to the end of the URL to change how the message is displayed. If `ispopout` is not present or if it is set to `1`, then the message is shown in a popout window. If `ispopout` is set to `0`, the browser shows the message in the Outlook on the web review pane.The message opens in the browser if you are signed in to your mailbox via Outlook on the web. You are prompted to sign in if you are not already signed in with the browser.This URL cannot be accessed from within an iFrame.**NOTE:** When using this URL to access a message from a mailbox with delegate permissions, both the signed-in user and the target mailbox must be in the same database region. For example, an error is returned when a user with a mailbox in the EUR (Europe) region attempts to access messages from a mailbox in the NAM (North America) region. |

## Relationships

| Relationship | Type | Description |
| --- | --- | --- |
| attachments | [attachment](attachment) collection | The [fileAttachment](fileattachment) and [itemAttachment](itemattachment) attachments for the message. |
| extensions | [extension](extension) collection | The collection of open extensions defined for the message. Nullable. |
| multiValueExtendedProperties | [multiValueLegacyExtendedProperty](multivaluelegacyextendedproperty) collection | The collection of multi-value extended properties defined for the message. Nullable. |
| singleValueExtendedProperties | [singleValueLegacyExtendedProperty](singlevaluelegacyextendedproperty) collection | The collection of single-value extended properties defined for the message. Nullable. |

## JSON representation

The following JSON representation shows the resource type.

```json
{
  "bccRecipients": [{"@odata.type": "microsoft.graph.recipient"}],
  "body": {"@odata.type": "microsoft.graph.itemBody"},
  "bodyPreview": "string",
  "categories": ["string"],
  "ccRecipients": [{"@odata.type": "microsoft.graph.recipient"}],
  "changeKey": "string",
  "conversationId": "string",
  "conversationIndex": "String (binary)",
  "createdDateTime": "String (timestamp)",
  "flag": {"@odata.type": "microsoft.graph.followupFlag"},
  "from": {"@odata.type": "microsoft.graph.recipient"},
  "hasAttachments": true,
  "id": "string (identifier)",
  "importance": "String",
  "inferenceClassification": "String",
  "internetMessageHeaders": [{"@odata.type": "microsoft.graph.internetMessageHeader"}],
  "internetMessageId": "String",
  "isDeliveryReceiptRequested": true,
  "isDraft": true,
  "isRead": true,
  "isReadReceiptRequested": true,
  "lastModifiedDateTime": "String (timestamp)",
  "parentFolderId": "string",
  "receivedDateTime": "String (timestamp)",
  "replyTo": [{"@odata.type": "microsoft.graph.recipient"}],
  "sender": {"@odata.type": "microsoft.graph.recipient"},
  "sentDateTime": "String (timestamp)",
  "subject": "string",
  "toRecipients": [{"@odata.type": "microsoft.graph.recipient"}],
  "uniqueBody": {"@odata.type": "microsoft.graph.itemBody"},
  "webLink": "string",

  "attachments": [{"@odata.type": "microsoft.graph.attachment"}],
  "extensions": [{"@odata.type": "microsoft.graph.extension"}],
  "multiValueExtendedProperties": [{"@odata.type": "microsoft.graph.multiValueLegacyExtendedProperty"}],
  "singleValueExtendedProperties": [{"@odata.type": "microsoft.graph.singleValueLegacyExtendedProperty"}]
}

```

---

## Other Supported Versions

- [graph-rest-beta](https://learn.microsoft.com/en-us/graph/api/resources/message?view=graph-rest-beta&accept=text/markdown)
